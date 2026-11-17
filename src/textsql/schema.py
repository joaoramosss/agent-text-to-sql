"""Descrição do schema para o LLM: DDL gerado do banco + notas de negócio escritas à mão.

O DDL dá nomes e tipos exatos. As notas dão o que o DDL não tem: o que cada tabela
significa, como fazer os joins e as pegadinhas do dataset. Text-to-SQL erra mais por
não entender o negócio do que por não saber SQL.
"""

from __future__ import annotations

from pathlib import Path

from textsql.db import Database

NOTES_PATH = Path(__file__).parent / "prompts" / "schema_notes.md"


def schema_ddl(db: Database) -> str:
    """Gera `CREATE TABLE ...` para cada tabela, a partir do information_schema."""
    statements = []
    for table in db.tables():
        cols = ",\n".join(f"  {name} {dtype}" for name, dtype in db.columns(table))
        statements.append(f"CREATE TABLE {table} (\n{cols}\n);")
    return "\n\n".join(statements)


def schema_notes() -> str:
    return NOTES_PATH.read_text(encoding="utf-8")


def schema_description(db: Database) -> str:
    """Texto completo que vai no prompt do agente."""
    return f"## Tabelas (DDL)\n\n```sql\n{schema_ddl(db)}\n```\n\n{schema_notes()}"
