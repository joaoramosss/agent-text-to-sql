import pytest

from textsql.errors import SQLError
from textsql.sql_utils import extract_sql, no_sql_reason


def test_bloco_sql():
    text = "Claro!\n```sql\nSELECT 1 AS x;\n```\nPronto."
    assert extract_sql(text) == "SELECT 1 AS x"


def test_bloco_sem_linguagem():
    assert extract_sql("```\nSELECT 2\n```") == "SELECT 2"


def test_sem_bloco_pega_do_select_em_diante():
    text = "Aqui está a consulta: SELECT count(*) FROM orders WHERE x = 1"
    assert extract_sql(text) == "SELECT count(*) FROM orders WHERE x = 1"


def test_with_cte_sem_bloco():
    text = "WITH t AS (SELECT 1) SELECT * FROM t"
    assert extract_sql(text) == text


def test_usa_o_primeiro_bloco():
    text = "```sql\nSELECT 1\n```\ne alternativa:\n```sql\nSELECT 2\n```"
    assert extract_sql(text) == "SELECT 1"


def test_sem_sql_e_erro_corrigivel():
    with pytest.raises(SQLError, match="Não encontrei SQL"):
        extract_sql("Não sei responder isso.")


@pytest.mark.parametrize(
    "text",
    [
        "SEM_SQL: Não há dados de clima.",
        "  sem_sql: Não há dados de clima.",
        "`SEM_SQL: Não há dados de clima.`",
    ],
)
def test_marcador_sem_sql(text):
    assert no_sql_reason(text) == "Não há dados de clima."


def test_marcador_sem_motivo_tem_texto_padrao():
    assert no_sql_reason("SEM_SQL:")


def test_resposta_com_sql_nao_e_sem_sql():
    assert no_sql_reason("```sql\nSELECT 1\n```") is None
