from conftest import SLOW_SQL, FakeLLM

from textsql.agent import Agent
from textsql.errors import LLMError


def sql_block(sql: str) -> str:
    return f"```sql\n{sql}\n```"


COUNT = sql_block("SELECT count(*) AS qtd_pedidos FROM orders")
BAD_COLUMN = sql_block("SELECT nope FROM orders")
SLOW = sql_block(SLOW_SQL)


# --- caminho feliz ----------------------------------------------------------------------------


def test_fluxo_completo(mini_db):
    llm = FakeLLM(COUNT, "Há 2 pedidos no total.")
    result = Agent(llm, mini_db).ask("Quantos pedidos existem?")

    assert result.status == "ok" and result.ok
    assert result.sql == "SELECT count(*) AS qtd_pedidos FROM orders"
    assert result.rows["qtd_pedidos"][0] == 2
    assert result.answer == "Há 2 pedidos no total."
    assert [a.error for a in result.attempts] == [None]
    assert len(llm.calls) == 2


def test_prompt_de_sql_leva_schema_e_pergunta(mini_db):
    llm = FakeLLM(COUNT, "ok")
    Agent(llm, mini_db).ask("Quantos pedidos existem?")

    system, user = llm.calls[0]
    assert system["role"] == "system"
    assert "CREATE TABLE orders (" in system["content"]
    assert "## Pegadinhas" in system["content"]
    assert "{schema}" not in system["content"]
    assert user == {"role": "user", "content": "Quantos pedidos existem?"}


def test_prompt_de_resposta_leva_sql_e_resultado(mini_db):
    llm = FakeLLM(COUNT, "ok")
    Agent(llm, mini_db).ask("Quantos pedidos existem?")

    user = llm.calls[1][1]["content"]
    assert "Pergunta: Quantos pedidos existem?" in user
    assert "SELECT count(*) AS qtd_pedidos FROM orders" in user
    assert "Resultado: 1 linha(s)" in user
    assert "qtd_pedidos\n2" in user


def test_resposta_recebe_so_uma_amostra(mini_db):
    llm = FakeLLM(sql_block("SELECT order_id FROM orders ORDER BY order_id"), "ok")
    Agent(llm, mini_db, sample_rows=1).ask("liste os pedidos")

    user = llm.calls[1][1]["content"]
    assert "Resultado: 2 linha(s), mostrando as primeiras 1" in user
    assert "o1" in user and "o2" not in user


def test_resultado_vazio_e_sinalizado(mini_db):
    llm = FakeLLM(sql_block("SELECT * FROM orders WHERE 1 = 0"), "ok")
    Agent(llm, mini_db).ask("x")
    assert "(vazio)" in llm.calls[1][1]["content"]


def test_limite_de_linhas_e_avisado(mini_db):
    llm = FakeLLM(sql_block("SELECT order_id FROM orders"), "ok")
    result = Agent(llm, mini_db, max_rows=1).ask("liste os pedidos")

    assert result.truncated and len(result.rows) == 1
    assert "cortado no limite de 1 linhas" in llm.calls[1][1]["content"]


# --- autocorreção -----------------------------------------------------------------------------


def test_corrige_sql_com_erro(mini_db):
    llm = FakeLLM(BAD_COLUMN, COUNT, "Há 2 pedidos.")
    result = Agent(llm, mini_db).ask("Quantos pedidos existem?")

    assert result.status == "ok"
    assert len(result.attempts) == 2
    assert "nope" in result.attempts[0].error and result.attempts[1].error is None
    # a 2ª chamada é a mesma conversa + a resposta errada + o erro
    retry = llm.calls[1]
    assert retry[2] == {"role": "assistant", "content": BAD_COLUMN}
    assert retry[3]["role"] == "user" and "nope" in retry[3]["content"]
    assert "```sql" in retry[3]["content"]


def test_esgota_tentativas(mini_db):
    llm = FakeLLM(BAD_COLUMN, BAD_COLUMN, BAD_COLUMN)
    result = Agent(llm, mini_db, max_attempts=3).ask("x")

    assert result.status == "failed" and not result.ok
    assert len(result.attempts) == 3
    assert result.rows is None
    assert "3 tentativas" in result.answer
    assert len(llm.calls) == 3  # não chama o passo de resposta


def test_resposta_sem_sql_tenta_de_novo(mini_db):
    llm = FakeLLM("Acho que são 2 pedidos.", COUNT, "ok")
    result = Agent(llm, mini_db).ask("Quantos pedidos existem?")

    assert result.status == "ok"
    assert result.attempts[0].sql == "" and "Não encontrei SQL" in result.attempts[0].error


def test_timeout_volta_para_o_modelo(mini_db):
    llm = FakeLLM(SLOW, COUNT, "ok")
    result = Agent(llm, mini_db, timeout_s=0.2).ask("x")

    assert result.status == "ok"
    assert "interrompida" in result.attempts[0].error


# --- bloqueio e perguntas fora do escopo -------------------------------------------------------


def test_sql_perigoso_bloqueia_sem_tentar_de_novo(mini_db):
    llm = FakeLLM(sql_block("DROP TABLE orders"))
    result = Agent(llm, mini_db).ask("apague a tabela de pedidos")

    assert result.status == "blocked"
    assert result.sql == "DROP TABLE orders"
    assert "DROP" in result.attempts[0].error
    assert len(llm.calls) == 1


def test_pergunta_fora_do_escopo(mini_db):
    llm = FakeLLM("SEM_SQL: O banco não tem dados de clima.")
    result = Agent(llm, mini_db).ask("Vai chover amanhã?")

    assert result.status == "unanswerable"
    assert result.answer == "O banco não tem dados de clima."
    assert result.sql is None and result.attempts == []
    assert len(llm.calls) == 1


# --- falha do LLM --------------------------------------------------------------------------------


class FailingAnswerLLM(FakeLLM):
    """Gera o SQL e falha no passo da resposta, como numa queda de rede ou cota estourada."""

    def complete(self, messages, *, temperature=0.0):
        if len(self.calls) == 1:
            self.calls.append(messages)
            raise LLMError("RateLimitError: limite de requisições")
        return super().complete(messages, temperature=temperature)


def test_falha_do_llm_na_resposta_ainda_entrega_a_tabela(mini_db):
    result = Agent(FailingAnswerLLM(COUNT), mini_db).ask("Quantos pedidos existem?")

    assert result.status == "ok"
    assert result.rows["qtd_pedidos"][0] == 2
    assert "Veja a tabela" in result.answer
