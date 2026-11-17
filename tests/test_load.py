import pytest

from textsql.db import Database
from textsql.load import TABLES, load_olist


def test_cria_todas_as_tabelas(mini_db):
    assert mini_db.tables() == sorted(TABLES.values())


def test_cep_preserva_zero_a_esquerda(mini_db):
    zips = mini_db.query("SELECT customer_zip_code_prefix AS z FROM customers ORDER BY z")["z"]
    assert list(zips) == ["01003", "20000"]
    assert dict(mini_db.columns("customers"))["customer_zip_code_prefix"] == "VARCHAR"


def test_timestamps_sao_tipados(mini_db):
    assert dict(mini_db.columns("orders"))["order_purchase_timestamp"] == "TIMESTAMP"


def test_geolocation_agregada_por_cep(mini_db):
    df = mini_db.query(
        "SELECT geolocation_zip_code_prefix AS z, geolocation_lat AS lat, geolocation_city AS c "
        "FROM geolocation ORDER BY z"
    )
    assert list(df["z"]) == ["01003", "20000"]  # 3 linhas brutas viraram 2
    assert df["lat"][0] == pytest.approx(-23.55)
    assert df["c"][0] == "sao paulo"


def test_carga_e_idempotente(mini_source, tmp_path):
    db_path = tmp_path / "x.duckdb"
    first = load_olist(mini_source, db_path)
    second = load_olist(mini_source, db_path)
    assert first == second
    with Database(db_path) as db:
        assert db.query("SELECT count(*) AS n FROM orders")["n"][0] == 2


def test_falha_claro_se_faltar_csv(tmp_path):
    with pytest.raises(FileNotFoundError, match="olist_orders_dataset.csv"):
        load_olist(tmp_path, tmp_path / "x.duckdb")
