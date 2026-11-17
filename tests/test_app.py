"""Teste da interface Streamlit de ponta a ponta, sem navegador e sem rede.

O `AppTest` executa o script do app em memória; o `build_agent` é trocado por um agente com
LLM falso sobre o Olist em miniatura.
"""

import json

import pytest
import streamlit as st
from conftest import FakeLLM
from streamlit.testing.v1 import AppTest

import textsql.agent
from textsql.agent import Agent
from textsql.config import PROJECT_ROOT

APP = str(PROJECT_ROOT / "streamlit_app.py")


@pytest.fixture
def use_fake_agent(monkeypatch, mini_db):
    def install(*answers):
        llm = FakeLLM(*answers)
        monkeypatch.setattr(textsql.agent, "build_agent", lambda: Agent(llm, mini_db))
        return llm

    st.cache_resource.clear()  # o agente fica em cache entre execuções do app
    yield install
    st.cache_resource.clear()


def run_question(question: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.chat_input[0].set_value(question).run()
    return at


def test_tela_inicial(use_fake_agent):
    use_fake_agent()
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "Analista de dados Olist"
    assert len(at.chat_input) == 1


def test_pergunta_mostra_resposta_metrica_e_sql(use_fake_agent):
    use_fake_agent("```sql\nSELECT count(*) AS qtd_pedidos FROM orders\n```", "São R$ 2 pedidos.")
    at = run_question("Quantos pedidos?")

    assert not at.exception
    assert any("R\\$ 2 pedidos" in m.value for m in at.markdown)  # $ escapado
    assert at.metric[0].value == "2"
    assert any("count(*)" in c.value for c in at.code)
    assert len(at.session_state["history"]) == 1
    # detalhes: linha do tempo das etapas + resumo do trace
    trace = at.session_state["history"][0].trace
    assert any(trace.trace_id in c.value for c in at.caption)
    assert len(at.dataframe) == 2  # tabela de dados (no expander) + linha do tempo das etapas


def test_ranking_vira_grafico_de_barras(use_fake_agent):
    sql = "SELECT order_status AS status, count(*) AS n FROM orders GROUP BY 1 ORDER BY 1"
    use_fake_agent(f"```sql\n{sql}\n```", "ok")
    at = run_question("pedidos por status")

    assert not at.exception
    charts = at.get("vega_lite_chart")
    assert len(charts) == 1
    assert json.loads(charts[0].proto.spec)["mark"]["type"] == "bar"
    assert len(at.dataframe) == 2  # a tabela de dados aparece junto (+ a das etapas)


def test_bloqueio_aparece_como_aviso(use_fake_agent):
    use_fake_agent("```sql\nDROP TABLE orders\n```")
    at = run_question("apague tudo")

    assert not at.exception
    assert "Consulta bloqueada" in at.warning[0].value


def test_botao_de_exemplo_faz_a_pergunta(use_fake_agent):
    llm = use_fake_agent("SEM_SQL: Exemplo fora do escopo.")
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.button[0].click().run()

    assert not at.exception
    assert llm.calls[0][-1]["content"] == "Quais as 10 categorias com maior receita?"
    assert at.info[0].value == "Exemplo fora do escopo."
