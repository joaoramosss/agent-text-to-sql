import duckdb
import pytest
from conftest import FakeLLM

from textsql.agent import Agent

SQL_ANSWER = "```sql\nSELECT count(*) AS qtd_pedidos FROM orders\n```"


def test_fluxo_completo(mini_db):
    llm = FakeLLM(SQL_ANSWER, "Há 2 pedidos no total.")
    result = Agent(llm, mini_db).ask("Quantos pedidos existem?")

    assert result.sql == "SELECT count(*) AS qtd_pedidos FROM orders"
    assert result.rows["qtd_pedidos"][0] == 2
    assert result.answer == "Há 2 pedidos no total."
    assert len(llm.calls) == 2


def test_prompt_de_sql_leva_schema_e_pergunta(mini_db):
    llm = FakeLLM(SQL_ANSWER, "ok")
    Agent(llm, mini_db).ask("Quantos pedidos existem?")

    system, user = llm.calls[0]
    assert system["role"] == "system"
    assert "CREATE TABLE orders (" in system["content"]
    assert "## Pegadinhas" in system["content"]
    assert "{schema}" not in system["content"]
    assert user == {"role": "user", "content": "Quantos pedidos existem?"}


def test_prompt_de_resposta_leva_sql_e_resultado(mini_db):
    llm = FakeLLM(SQL_ANSWER, "ok")
    Agent(llm, mini_db).ask("Quantos pedidos existem?")

    user = llm.calls[1][1]["content"]
    assert "Pergunta: Quantos pedidos existem?" in user
    assert "SELECT count(*) AS qtd_pedidos FROM orders" in user
    assert "Resultado: 1 linha(s)" in user
    assert "qtd_pedidos\n2" in user


def test_resposta_recebe_so_uma_amostra(mini_db):
    llm = FakeLLM("```sql\nSELECT order_id FROM orders ORDER BY order_id\n```", "ok")
    Agent(llm, mini_db, sample_rows=1).ask("liste os pedidos")

    user = llm.calls[1][1]["content"]
    assert "Resultado: 2 linha(s), mostrando as primeiras 1" in user
    assert "o1" in user and "o2" not in user


def test_resultado_vazio_e_sinalizado(mini_db):
    llm = FakeLLM("```sql\nSELECT * FROM orders WHERE 1 = 0\n```", "ok")
    Agent(llm, mini_db).ask("x")
    assert "(vazio)" in llm.calls[1][1]["content"]


def test_sql_invalido_sobe_erro_do_duckdb(mini_db):
    llm = FakeLLM("```sql\nSELECT * FROM tabela_inexistente\n```")
    with pytest.raises(duckdb.Error):
        Agent(llm, mini_db).ask("x")
    assert len(llm.calls) == 1  # não chegou a pedir resposta
