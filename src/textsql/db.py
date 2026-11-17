"""Acesso ao banco DuckDB. Por padrão abre em modo somente leitura."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from textsql.config import load_settings


class Database:
    def __init__(self, path: Path | None = None, *, read_only: bool = True):
        self.path = Path(path) if path else load_settings().db_path
        if not self.path.exists():
            raise FileNotFoundError(
                f"Banco não encontrado em {self.path}. Rode: uv run python scripts/load_data.py"
            )
        self._con = duckdb.connect(str(self.path), read_only=read_only)

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        return self._con.execute(sql, params).df()

    def tables(self) -> list[str]:
        rows = self._con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
        return [r[0] for r in rows]

    def columns(self, table: str) -> list[tuple[str, str]]:
        """[(nome, tipo), ...] na ordem do CREATE TABLE."""
        rows = self._con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
            [table],
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
