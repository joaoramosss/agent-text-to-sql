"""Acesso ao banco DuckDB, com as proteções que dependem do próprio motor.

Esta é a camada mais forte dos guardrails: mesmo que um SQL perigoso passe pela validação
(`guardrails.py`), o DuckDB recusa escrever, ler arquivos ou acessar a rede.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from textsql.config import load_settings
from textsql.errors import QueryTimeoutError, SQLError, UnsafeSQLError

# Configuração aplicada na abertura do banco e travada em seguida.
SAFE_CONFIG: dict[str, bool] = {
    # sem arquivos nem rede: bloqueia read_csv('...'), COPY ... TO, INSTALL, ATTACH de arquivo
    "enable_external_access": False,
    "autoinstall_known_extensions": False,
    "autoload_known_extensions": False,
    # o DuckDB em Python consegue ler variáveis do processo (DataFrames) pelo nome; desliga
    "python_enable_replacements": False,
    # ninguém, nem o SQL do LLM, consegue desfazer o que está acima com SET
    "lock_configuration": True,
}


@dataclass
class QueryResult:
    rows: pd.DataFrame
    truncated: bool  # True se havia mais linhas do que o limite


class Database:
    def __init__(self, path: Path | None = None, *, read_only: bool = True):
        self.path = Path(path) if path else load_settings().db_path
        if not self.path.exists():
            raise FileNotFoundError(
                f"Banco não encontrado em {self.path}. Rode: uv run python scripts/load_data.py"
            )
        self._con = duckdb.connect(str(self.path), read_only=read_only, config=SAFE_CONFIG)

    def query(self, sql: str, params: list | None = None) -> pd.DataFrame:
        """SQL confiável, escrito no código (schema, testes). O SQL do LLM passa por `run`."""
        with self._con.cursor() as cur:
            return cur.execute(sql, params).df()

    def run(self, sql: str, *, max_rows: int, timeout_s: float) -> QueryResult:
        """Executa SQL não confiável (gerado pelo LLM) com limite de linhas e de tempo.

        - Limite: envolve a consulta em `SELECT * FROM (...) LIMIT max_rows + 1`. Se vier a linha
          extra, o resultado foi cortado, e sabemos disso sem contar tudo. O DuckDB empurra o
          LIMIT para dentro (Top N), então a ordem do ORDER BY original é mantida.
        - Um único SELECT: o parser do próprio DuckDB confere o texto final antes de executar.
          O sqlglot pode divergir do DuckDB em casos raros; aqui quem decide é o motor.
        - Tempo: um timer chama `interrupt()` se a consulta passar de `timeout_s`.
        - Cada chamada usa um cursor próprio: seguro com várias threads (ex.: Streamlit), e o
          interrupt atinge só esta consulta.
        """
        # quebra de linha antes do ")": um comentário "-- ..." no fim do SQL não engole o parêntese
        wrapped = f"SELECT * FROM (\n{sql}\n) AS resultado LIMIT {max_rows + 1}"
        with self._con.cursor() as cur:
            _ensure_single_select(cur, wrapped)
            timer = threading.Timer(timeout_s, cur.interrupt)
            timer.start()
            try:
                df = cur.execute(wrapped).df()
            except duckdb.InterruptException as exc:
                raise QueryTimeoutError(
                    f"A consulta passou de {timeout_s:g}s e foi interrompida. "
                    "Confira se todo JOIN tem condição e simplifique a consulta."
                ) from exc
            except duckdb.Error as exc:
                raise SQLError(str(exc)) from exc
            finally:
                timer.cancel()
        return QueryResult(rows=df.head(max_rows), truncated=len(df) > max_rows)

    def tables(self) -> list[str]:
        rows = self.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        )
        return rows["table_name"].tolist()

    def columns(self, table: str) -> list[tuple[str, str]]:
        """[(nome, tipo), ...] na ordem do CREATE TABLE."""
        rows = self.query(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
            [table],
        )
        return list(zip(rows["column_name"], rows["data_type"], strict=True))

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _ensure_single_select(cur: duckdb.DuckDBPyConnection, sql: str) -> None:
    try:
        statements = cur.extract_statements(sql)
    except duckdb.Error as exc:
        raise SQLError(str(exc)) from exc
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise UnsafeSQLError("O banco só executa um único SELECT.")
