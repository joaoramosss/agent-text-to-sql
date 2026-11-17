"""Testes contra o banco real. Pulam se `data/olist.duckdb` ainda não foi gerado."""

import pytest

from textsql.config import load_settings
from textsql.db import Database


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


def test_conexao_e_somente_leitura(real_db):
    with pytest.raises(Exception, match="read-only"):
        real_db.query("CREATE TABLE x AS SELECT 1")
