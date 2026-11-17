import pytest

from textsql.errors import SQLError, UnsafeSQLError
from textsql.guardrails import validate_sql
from textsql.load import TABLES

ALLOWED = list(TABLES.values())

# Consultas legítimas que precisam passar. Um guardrail que bloqueia demais também é um bug.
SAFE = [
    "SELECT count(*) FROM orders",
    "select * from ORDERS",
    "SELECT 'drop table orders; delete' AS texto",
    "WITH t AS (SELECT order_id FROM orders) SELECT count(*) FROM t",
    "WITH a AS (SELECT 1 AS x), b AS (SELECT x FROM a) SELECT * FROM b",
    "SELECT order_status FROM orders UNION ALL SELECT payment_type FROM order_payments",
    "SELECT * FROM (SELECT customer_state, count(*) AS n FROM customers GROUP BY 1) AS s",
    "SELECT (SELECT max(price) FROM order_items) AS maior_preco",
    "SELECT o.order_id FROM orders o JOIN customers c ON o.customer_id = c.customer_id",
    "SELECT * FROM main.orders",
    "FROM orders SELECT count(*)",
    "SELECT date_trunc('month', order_purchase_timestamp) AS mes, count(*) FROM orders GROUP BY 1",
    "SELECT * FROM range(12) AS t(mes)",
    "SELECT unnest(['a', 'b']) AS letra",
    "SELECT 1 AS x -- comentário no fim",
    "SELECT count(*) FROM orders;",
]

# Tem que ser bloqueado e NÃO voltar para o LLM tentar de novo.
UNSAFE = [
    "DROP TABLE orders",
    "DELETE FROM orders",
    "INSERT INTO orders VALUES ('x')",
    "UPDATE orders SET order_status = 'x'",
    "CREATE TABLE x AS SELECT 1",
    "CREATE TEMP TABLE x AS SELECT 1",  # o DuckDB aceita isso mesmo em read-only
    "ALTER TABLE orders ADD COLUMN y INT",
    "COPY orders TO 'vazamento.csv'",
    "ATTACH 'outro.db' AS outro",
    "INSTALL httpfs",
    "LOAD httpfs",
    "PRAGMA database_list",
    "SET enable_external_access = true",
    "CALL pragma_version()",
    "CHECKPOINT",
    "SELECT 1; DROP TABLE orders",
    "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
    "SELECT * INTO copia FROM orders",
    "SELECT * FROM read_csv('C:/Users/alguem/.env')",
    "SELECT * FROM read_text('.env')",
    "SELECT * FROM read_parquet('s3://bucket/dados.parquet')",
    "SELECT * FROM glob('*')",
    "SELECT * FROM query('SELECT 1')",
    "SELECT * FROM duckdb_settings()",
    "SELECT getenv('GROQ_API_KEY')",
    "SELECT * FROM 'data/olist.duckdb'",
    'SELECT * FROM "C:/Users/alguem/segredo.csv"',
    "SELECT (SELECT content FROM read_text('.env')) AS x",
]

# Erros que o LLM consegue corrigir: voltam para ele com a mensagem.
FIXABLE = [
    "SELEC count(*) FROM orders",
    "SELECT * FROM",
    "SELECT * FROM pedidos",
    "SELECT * FROM information_schema.tables",
    "SELECT 1; SELECT 2",
    "",
]


@pytest.mark.parametrize("sql", SAFE)
def test_consulta_legitima_passa(sql):
    validate_sql(sql, ALLOWED)


@pytest.mark.parametrize("sql", UNSAFE)
def test_sql_perigoso_e_bloqueado(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql, ALLOWED)


@pytest.mark.parametrize("sql", FIXABLE)
def test_erro_corrigivel_nao_e_bloqueio(sql):
    with pytest.raises(SQLError):
        validate_sql(sql, ALLOWED)


def test_bloqueio_e_corrigivel_sao_excecoes_separadas():
    # o agente faz `except SQLError` para tentar de novo; um bloqueio não pode cair ali
    assert not issubclass(UnsafeSQLError, SQLError)


def test_tabela_desconhecida_lista_as_disponiveis():
    with pytest.raises(SQLError, match="Tabela desconhecida: pedidos.*orders"):
        validate_sql("SELECT * FROM pedidos", ALLOWED)


def test_mensagem_de_bloqueio_diz_o_comando():
    with pytest.raises(UnsafeSQLError, match="DROP"):
        validate_sql("DROP TABLE orders", ALLOWED)
