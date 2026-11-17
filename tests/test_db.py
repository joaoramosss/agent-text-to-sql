"""Banco: limite de linhas, timeout e as proteções do próprio DuckDB.

Os testes de contagem usam o banco real e pulam se `data/olist.duckdb` não foi gerado.
"""

from concurrent.futures import ThreadPoolExecutor

import duckdb
import pytest
from conftest import SLOW_SQL

from textsql.config import load_settings
from textsql.db import Database
from textsql.errors import QueryTimeoutError, SQLError, UnsafeSQLError


@pytest.fixture
def real_db():
    path = load_settings().db_path
    if not path.exists():
        pytest.skip("banco real não gerado; rode scripts/load_data.py")
    with Database(path) as db:
        yield db


def test_banco_inexistente_da_erro_claro(tmp_path):
    with pytest.raises(FileNotFoundError, match="load_data.py"):
        Database(tmp_path / "nao_existe.duckdb")


def test_contagens_do_olist(real_db):
    n = real_db.query("SELECT count(*) AS n FROM orders")["n"][0]
    assert n == 99_441
    geo = real_db.query("SELECT count(*) AS n FROM geolocation")["n"][0]
    assert 18_000 < geo < 20_000


# --- camada do motor: vale mesmo que o SQL nem passe pelos guardrails -------------------------


def test_conexao_e_somente_leitura(mini_db):
    with pytest.raises(duckdb.Error, match="read-only"):
        mini_db.query("CREATE TABLE x AS SELECT 1")


def test_motor_nao_le_arquivos(mini_db, mini_source):
    csv = (mini_source / "olist_orders_dataset.csv").as_posix()
    with pytest.raises(duckdb.PermissionException):
        mini_db.query(f"SELECT * FROM read_csv('{csv}')")


def test_configuracao_travada(mini_db):
    with pytest.raises(duckdb.Error, match="locked"):
        mini_db.query("SET enable_external_access = true")


# --- run(): limite de linhas ------------------------------------------------------------------


def test_run_corta_no_limite_e_avisa(mini_db):
    result = mini_db.run("SELECT * FROM orders", max_rows=1, timeout_s=5)
    assert len(result.rows) == 1
    assert result.truncated


def test_run_sem_corte_quando_cabe(mini_db):
    result = mini_db.run("SELECT * FROM orders", max_rows=2, timeout_s=5)
    assert len(result.rows) == 2
    assert not result.truncated


def test_run_mantem_a_ordem_do_order_by(mini_db):
    sql = "SELECT order_id FROM orders ORDER BY order_id DESC"
    result = mini_db.run(sql, max_rows=1, timeout_s=5)
    assert result.rows["order_id"].tolist() == ["o2"]


def test_run_aceita_comentario_no_fim(mini_db):
    result = mini_db.run("SELECT 1 AS x -- comentário", max_rows=10, timeout_s=5)
    assert result.rows["x"].tolist() == [1]


# --- run(): erros, timeout e o parser do DuckDB --------------------------------------------------


def test_run_traduz_erro_do_duckdb_para_sqlerror(mini_db):
    with pytest.raises(SQLError, match="nope"):
        mini_db.run("SELECT nope FROM orders", max_rows=10, timeout_s=5)


def test_run_interrompe_consulta_lenta(mini_db):
    with pytest.raises(QueryTimeoutError, match="0.2s"):
        mini_db.run(SLOW_SQL, max_rows=10, timeout_s=0.2)
    # a conexão continua utilizável depois do interrupt
    assert mini_db.run("SELECT 1 AS x", max_rows=10, timeout_s=5).rows["x"][0] == 1


def test_run_recusa_fuga_do_parentese(mini_db):
    # tenta fechar o "SELECT * FROM (" do envelope e emendar outro comando
    sql = "SELECT 1) AS q; DROP TABLE orders; SELECT * FROM (SELECT 1"
    with pytest.raises(UnsafeSQLError):
        mini_db.run(sql, max_rows=10, timeout_s=5)


def test_run_em_varias_threads(mini_db):
    # cada chamada usa um cursor próprio; o Streamlit atende sessões em threads diferentes
    def count(_):
        result = mini_db.run("SELECT count(*) AS n FROM orders", max_rows=10, timeout_s=5)
        return result.rows["n"][0]

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(count, range(8))) == [2] * 8
