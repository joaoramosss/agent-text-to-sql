import re

from textsql.load import TABLES
from textsql.schema import schema_ddl, schema_description, schema_notes


def test_ddl_tem_todas_as_tabelas(mini_db):
    ddl = schema_ddl(mini_db)
    for table in TABLES.values():
        assert f"CREATE TABLE {table} (" in ddl
    assert "order_purchase_timestamp TIMESTAMP" in ddl


def test_notas_mencionam_todas_as_tabelas():
    notes = schema_notes()
    for table in TABLES.values():
        assert re.search(rf"\*\*{table}\*\*", notes), f"{table} sem descrição em schema_notes.md"


def test_descricao_completa_junta_ddl_e_notas(mini_db):
    text = schema_description(mini_db)
    assert "```sql" in text and "## Pegadinhas" in text
