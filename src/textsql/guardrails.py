"""Validação do SQL gerado pelo LLM, antes de executar.

Defesa em camadas (da mais fraca para a mais forte):
1. Prompt: pede só SELECT. O modelo pode desobedecer ou ser induzido pelo usuário.
2. Este módulo: analisa a árvore sintática (AST) com sqlglot e só deixa passar uma consulta de
   leitura, sobre as tabelas do schema, sem funções que acessem arquivos, rede ou ambiente.
3. Banco (`db.py`): conexão read-only, sem acesso externo, configuração travada; e o parser do
   próprio DuckDB confirma que é um único SELECT antes de executar.

Por que AST e não regex: regex procura texto. `SELECT 'drop table'` é inofensivo e uma regex
bloquearia; `WITH d AS (DELETE ...) SELECT ...` começa com WITH e uma regex deixaria passar.
A AST sabe o que é string, o que é comando e o que é nome de tabela.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from textsql.errors import SQLError, UnsafeSQLError

# O sqlglot avisa no log quando não reconhece um comando (ex.: LOAD) e o lê como "Command".
# Esse caso já é bloqueado abaixo; o aviso só poluiria o terminal.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

# Nós da AST que escrevem ou alteram algo. Procurados na árvore inteira, não só na raiz:
# `WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d` tem um SELECT na raiz.
WRITE_NODES = (exp.DML, exp.DDL, exp.Drop, exp.Alter, exp.TruncateTable)

# Funções de tabela permitidas no FROM: só geradores, que não leem nada de fora.
SAFE_TABLE_FUNCTIONS = {"range", "generate_series", "unnest"}

# Funções que leem arquivos, rede, variáveis de ambiente ou executam SQL dinâmico.
# A lista é incompleta por natureza; por isso a camada do banco desliga o acesso externo.
FORBIDDEN_FUNCTIONS = {"glob", "getenv", "query", "query_table", "sniff_csv", "st_read"}
FORBIDDEN_FUNCTION_PREFIXES = (
    "read_",
    "parquet_",
    "sqlite_",
    "postgres_",
    "mysql_",
    "iceberg_",
    "delta_",
)


def validate_sql(sql: str, allowed_tables: Iterable[str]) -> None:
    """Deixa passar só uma consulta de leitura sobre `allowed_tables`.

    Levanta `UnsafeSQLError` (bloqueio, não tenta de novo) ou `SQLError` (o LLM pode corrigir).
    """
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except (ParseError, TokenError) as exc:
        raise SQLError(f"SQL inválido: {_first_line(exc)}") from exc
    if not statements:
        raise SQLError("SQL vazio.")

    # todas primeiro: em "SELECT 1; DROP TABLE x" o problema é o DROP, não a contagem
    for statement in statements:
        _check_read_only(statement)
    if len(statements) > 1:
        raise SQLError(f"Envie uma única consulta (recebi {len(statements)}).")

    tree = statements[0]
    _check_functions(tree)
    _check_tables(tree, {t.lower() for t in allowed_tables})


def _check_read_only(statement: exp.Expression) -> None:
    # exp.Query = SELECT, UNION/INTERSECT/EXCEPT e consulta entre parênteses
    if not isinstance(statement, exp.Query):
        raise UnsafeSQLError(
            f"Apenas consultas de leitura (SELECT) são permitidas; recebi {_keyword(statement)}."
        )
    for node in statement.walk():
        if isinstance(node, WRITE_NODES):
            raise UnsafeSQLError(f"Comando de escrita dentro da consulta: {_keyword(node)}.")
        if isinstance(node, exp.Select) and node.args.get("into"):
            raise UnsafeSQLError("SELECT ... INTO cria uma tabela e não é permitido.")


def _check_functions(tree: exp.Expression) -> None:
    for func in tree.find_all(exp.Func):
        name = _func_name(func)
        if name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_FUNCTION_PREFIXES):
            raise UnsafeSQLError(
                f"Função não permitida: {name}() (acesso a arquivos, rede ou ambiente)."
            )


def _check_tables(tree: exp.Expression, allowed: set[str]) -> None:
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if isinstance(table.this, exp.Func):  # função de tabela no FROM: read_csv(...), range(...)
            name = _func_name(table.this)
            if name not in SAFE_TABLE_FUNCTIONS:
                raise UnsafeSQLError(f"Função de tabela não permitida no FROM: {name}().")
            continue

        name = table.name.lower()
        if _looks_like_path(name):  # FROM 'C:/arquivo.csv' faria o DuckDB ler o arquivo
            raise UnsafeSQLError(f"Leitura de arquivo não é permitida: {table.name}.")
        if table.catalog or table.db.lower() not in ("", "main"):
            raise SQLError(f"Use só as tabelas do schema, sem prefixo: {table.sql()}.")
        if name in cte_names or name in allowed:
            continue
        raise SQLError(
            f"Tabela desconhecida: {table.name}. Tabelas disponíveis: {', '.join(sorted(allowed))}."
        )


def _func_name(func: exp.Func) -> str:
    # funções conhecidas viram classes próprias (exp.ReadCSV); as demais, exp.Anonymous
    return (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()


def _looks_like_path(name: str) -> bool:
    return any(ch in name for ch in "./\\:")


def _keyword(node: exp.Expression) -> str:
    words = node.sql(dialect="duckdb").split(None, 1)
    return words[0].upper() if words else node.key.upper()


def _first_line(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0]
