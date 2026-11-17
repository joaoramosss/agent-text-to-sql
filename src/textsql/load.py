"""Carga do dataset Olist (CSVs do Kaggle) em um arquivo DuckDB.

Decisões:
- Tabelas materializadas (não views sobre CSV): carga única, consultas rápidas, um arquivo
  que a aplicação abre em modo somente leitura.
- Nomes limpos (`orders` em vez de `olist_orders_dataset`): menos tokens no prompt,
  menos chance de o LLM errar o nome.
- CEPs tipados explicitamente como VARCHAR: a inferência por amostra pode ler "01003" como 1003.
- `geolocation` agregada em 1 linha por prefixo de CEP (média de lat/lng): o CSV original tem
  ~1M linhas com várias coordenadas por CEP, e um join direto multiplicaria as linhas.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

# arquivo CSV -> nome da tabela
TABLES: dict[str, str] = {
    "olist_customers_dataset.csv": "customers",
    "olist_geolocation_dataset.csv": "geolocation",
    "olist_order_items_dataset.csv": "order_items",
    "olist_order_payments_dataset.csv": "order_payments",
    "olist_order_reviews_dataset.csv": "order_reviews",
    "olist_orders_dataset.csv": "orders",
    "olist_products_dataset.csv": "products",
    "olist_sellers_dataset.csv": "sellers",
    "product_category_name_translation.csv": "category_translation",
}

# tabela -> colunas cujo tipo não pode ficar por conta da inferência
COLUMN_TYPES: dict[str, dict[str, str]] = {
    "customers": {"customer_zip_code_prefix": "VARCHAR"},
    "sellers": {"seller_zip_code_prefix": "VARCHAR"},
    "geolocation": {"geolocation_zip_code_prefix": "VARCHAR"},
}

KAGGLE_DATASET = "olistbr/brazilian-ecommerce"


def download_olist() -> Path:
    """Baixa (ou reaproveita do cache) os CSVs do Kaggle. Não exige conta."""
    import kagglehub  # import local: só quem baixa precisa da dependência carregada

    return Path(kagglehub.dataset_download(KAGGLE_DATASET))


def _read_csv_expr(csv_path: Path, types: dict[str, str] | None = None) -> str:
    """Monta a expressão `read_csv(...)` do DuckDB para um arquivo."""
    path_literal = str(csv_path).replace("\\", "/").replace("'", "''")
    if not types:
        return f"read_csv('{path_literal}', header=true)"
    types_literal = ", ".join(f"'{col}': '{typ}'" for col, typ in types.items())
    return f"read_csv('{path_literal}', header=true, types={{{types_literal}}})"


def _geolocation_select(csv_path: Path) -> str:
    source = _read_csv_expr(csv_path, COLUMN_TYPES["geolocation"])
    return f"""
        SELECT
            geolocation_zip_code_prefix,
            avg(geolocation_lat)    AS geolocation_lat,
            avg(geolocation_lng)    AS geolocation_lng,
            mode(geolocation_city)  AS geolocation_city,
            mode(geolocation_state) AS geolocation_state
        FROM {source}
        GROUP BY geolocation_zip_code_prefix
    """


def load_olist(source_dir: Path, db_path: Path) -> dict[str, int]:
    """Recria `db_path` do zero com as tabelas do Olist. Devolve {tabela: linhas}."""
    missing = [f for f in TABLES if not (source_dir / f).exists()]
    if missing:
        raise FileNotFoundError(f"CSVs não encontrados em {source_dir}: {', '.join(missing)}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)  # carga idempotente: sempre parte do zero

    counts: dict[str, int] = {}
    with duckdb.connect(str(db_path)) as con:
        for csv_name, table in TABLES.items():
            csv_path = source_dir / csv_name
            if table == "geolocation":
                select = _geolocation_select(csv_path)
            else:
                select = f"SELECT * FROM {_read_csv_expr(csv_path, COLUMN_TYPES.get(table))}"
            con.execute(f"CREATE TABLE {table} AS {select}")
            counts[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return counts
