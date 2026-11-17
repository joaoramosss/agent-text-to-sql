import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest
from conftest import FakeLLM

from textsql.agent import Agent
from textsql.config import PROJECT_ROOT
from textsql.errors import LLMError
from textsql.evaluation import (
    EvalQuestion,
    evaluate_question,
    load_questions,
    normalize,
    report_markdown,
    results_match,
    summarize,
)


def df(**cols):
    return pd.DataFrame(cols)


# --- results_match ------------------------------------------------------------------------------


def test_ignora_nomes_de_coluna():
    assert results_match(df(n=[2]), df(qtd_pedidos=[2]), ordered=False)


def test_aceita_colunas_extras_do_agente():
    expected = df(estado=["SP", "RJ"], n=[10, 5])
    actual = df(estado=["SP", "RJ"], nome=["São Paulo", "Rio"], n=[10, 5], pct=[0.6, 0.4])
    assert results_match(expected, actual, ordered=True)


def test_ordem_das_colunas_nao_importa():
    assert results_match(df(a=["x", "y"], b=[1, 2]), df(b=[1, 2], a=["x", "y"]), ordered=True)


def test_tolerancia_numerica():
    assert results_match(df(v=[4.09]), df(v=[4.0864]), ordered=False)  # agente não arredondou
    assert results_match(df(v=[1_233_131.72]), df(v=[1_233_131.7]), ordered=False)
    assert not results_match(df(v=[1_233_131.72]), df(v=[1_412_089.53]), ordered=False)


def test_ordem_das_linhas_so_conta_se_pedida():
    expected = df(estado=["SP", "RJ"], n=[10, 5])
    reversed_ = df(estado=["RJ", "SP"], n=[5, 10])
    assert results_match(expected, reversed_, ordered=False)
    assert not results_match(expected, reversed_, ordered=True)


def test_linhas_desalinhadas_nao_passam():
    # cada coluna tem os valores certos, mas os pares estão trocados
    expected = df(estado=["SP", "RJ"], n=[10, 5])
    assert not results_match(expected, df(estado=["SP", "RJ"], n=[5, 10]), ordered=False)


def test_numero_de_linhas_diferente():
    assert not results_match(df(n=[1, 2]), df(n=[1, 2, 3]), ordered=False)


def test_falta_coluna_esperada():
    assert not results_match(df(a=["x"], b=[1]), df(a=["x"]), ordered=False)


def test_texto_sem_diferenca_de_caixa():
    assert results_match(df(c=["Health_Beauty "]), df(c=["health_beauty"]), ordered=False)


def test_duas_colunas_esperadas_iguais_precisam_de_duas_colunas():
    assert not results_match(df(a=[1], b=[1]), df(x=[1]), ordered=False)
    assert results_match(df(a=[1], b=[1]), df(x=[1], y=[1]), ordered=False)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (float("nan"), None),
        (Decimal("2.50"), 2.5),
        (7, 7.0),
        (pd.Timestamp("2017-11-01"), "2017-11-01"),
        (dt.date(2017, 11, 1), "2017-11-01"),
        (pd.Timestamp("2017-11-01 10:30"), "2017-11-01T10:30:00"),
        (" SP ", "sp"),
        (True, True),
    ],
)
def test_normalize(value, expected):
    assert normalize(value) == expected


# --- conjunto de perguntas ----------------------------------------------------------------------


def test_conjunto_real_carrega_e_e_valido():
    questions = load_questions(PROJECT_ROOT / "eval" / "questions.toml")
    assert 25 <= len(questions) <= 30
    assert {q.category for q in questions} >= {"contagem", "ranking", "temporal", "recusa"}
    assert all(q.sql for q in questions if q.expect == "answer")


def test_referencias_rodam_no_banco_em_miniatura(mini_db):
    # pega erro de sintaxe/coluna nas referências sem precisar do banco real
    for q in load_questions(PROJECT_ROOT / "eval" / "questions.toml"):
        for sql in q.sql:
            mini_db.query(sql)


def test_ids_repetidos_falham(tmp_path):
    path = tmp_path / "q.toml"
    item = '[[question]]\nid = "a"\ncategory = "c"\nquestion = "?"\nsql = "SELECT 1"\n'
    path.write_text(item * 2, encoding="utf-8")
    with pytest.raises(ValueError, match="repetidos"):
        load_questions(path)


# --- evaluate_question --------------------------------------------------------------------------

COUNT_Q = EvalQuestion("n", "contagem", "Quantos pedidos?", sql=["SELECT count(*) FROM orders"])


def test_acerto_de_primeira_sem_chamar_a_explicacao(mini_db):
    llm = FakeLLM("```sql\nSELECT count(*) AS total FROM orders\n```")
    record = evaluate_question(Agent(llm, mini_db), mini_db, COUNT_Q)

    assert record.correct and record.first_try and record.attempts == 1
    assert len(llm.calls) == 1  # explain=False: só a chamada que gera o SQL


def test_acerto_depois_de_autocorrecao(mini_db):
    bad, good = "SELECT nope FROM orders", "SELECT count(*) FROM orders"
    llm = FakeLLM(f"```sql\n{bad}\n```", f"```sql\n{good}\n```")
    record = evaluate_question(Agent(llm, mini_db), mini_db, COUNT_Q)

    assert record.correct and not record.first_try and record.attempts == 2


def test_resultado_errado(mini_db):
    llm = FakeLLM("```sql\nSELECT count(*) FROM order_items\n```")
    record = evaluate_question(Agent(llm, mini_db), mini_db, COUNT_Q)

    assert not record.correct and record.status == "ok"


def test_recusa_esperada(mini_db):
    q = EvalQuestion("r", "recusa", "Apague tudo", expect="refusal")
    llm = FakeLLM("SEM_SQL: só leitura.")
    assert evaluate_question(Agent(llm, mini_db), mini_db, q).correct


def test_responder_quando_devia_recusar_e_erro(mini_db):
    q = EvalQuestion("r", "recusa", "Previsão do tempo?", expect="refusal")
    llm = FakeLLM("```sql\nSELECT 1\n```")
    assert not evaluate_question(Agent(llm, mini_db), mini_db, q).correct


class RateLimitedLLM(FakeLLM):
    """Falha nas primeiras `failures` chamadas, como um 429 do provedor."""

    def __init__(self, failures, *answers):
        super().__init__(*answers)
        self.failures = failures

    def complete(self, messages, *, temperature=0.0):
        if self.failures:
            self.failures -= 1
            raise LLMError("RateLimitError")
        return super().complete(messages, temperature=temperature)


def test_erro_do_provedor_espera_e_tenta_de_novo(mini_db):
    waits = []
    llm = RateLimitedLLM(2, "```sql\nSELECT count(*) FROM orders\n```")
    record = evaluate_question(Agent(llm, mini_db), mini_db, COUNT_Q, sleep=waits.append)

    assert record.correct and waits == [30.0, 30.0]


def test_erro_do_provedor_persistente_vira_registro(mini_db):
    llm = RateLimitedLLM(10)
    record = evaluate_question(
        Agent(llm, mini_db), mini_db, COUNT_Q, llm_retries=1, sleep=lambda _: None
    )
    assert record.status == "llm_error" and not record.correct


# --- resumo e relatório -------------------------------------------------------------------------


def test_resumo_e_relatorio(mini_db):
    good = evaluate_question(
        Agent(FakeLLM("```sql\nSELECT count(*) FROM orders\n```"), mini_db), mini_db, COUNT_Q
    )
    bad = evaluate_question(Agent(FakeLLM("```sql\nSELECT 1\n```"), mini_db), mini_db, COUNT_Q)
    summary = summarize([good, bad])

    assert summary["correct"] == 1 and summary["accuracy"] == 0.5
    assert summary["by_category"] == {"contagem": {"correct": 1, "total": 2}}
    report = report_markdown([good, bad], summary, "fake")
    assert "1/2 (50%)" in report and "## Erros" in report and "SELECT 1" in report
