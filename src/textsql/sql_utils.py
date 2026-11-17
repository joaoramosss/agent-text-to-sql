"""Utilidades para lidar com o texto que o LLM devolve."""

from __future__ import annotations

import re

from textsql.errors import SQLError

_CODE_BLOCK = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_BARE_QUERY = re.compile(r"\b(WITH|SELECT)\b.*", re.DOTALL | re.IGNORECASE)

# Saída combinada no prompt para "essa pergunta não dá para responder com os dados"
NO_SQL_MARKER = "SEM_SQL:"


def extract_sql(text: str) -> str:
    """Extrai o SQL da resposta do modelo.

    Prefere o primeiro bloco de código; se não houver, pega do primeiro WITH/SELECT em diante.
    Remove o `;` final para facilitar compor a consulta depois (ex.: envolver em LIMIT).
    Sem SQL na resposta é um erro corrigível: o agente pede de novo.
    """
    match = _CODE_BLOCK.search(text)
    candidate = match.group(1) if match else ""
    if not candidate.strip():
        bare = _BARE_QUERY.search(text)
        candidate = bare.group(0) if bare else ""

    sql = candidate.strip().rstrip(";").strip()
    if not sql:
        raise SQLError(
            "Não encontrei SQL na resposta. Responda somente com a consulta em um bloco ```sql."
        )
    return sql


def no_sql_reason(text: str) -> str | None:
    """Se o modelo disse que a pergunta não tem resposta nos dados, devolve o motivo."""
    clean = text.strip().strip("`").strip()
    if not clean.upper().startswith(NO_SQL_MARKER):
        return None
    return clean[len(NO_SQL_MARKER) :].strip() or "Não dá para responder isso com estes dados."
