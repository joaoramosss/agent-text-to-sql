"""Utilidades para lidar com o texto que o LLM devolve."""

from __future__ import annotations

import re

_CODE_BLOCK = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_BARE_QUERY = re.compile(r"\b(WITH|SELECT)\b.*", re.DOTALL | re.IGNORECASE)


def extract_sql(text: str) -> str:
    """Extrai o SQL da resposta do modelo.

    Prefere o primeiro bloco de código; se não houver, pega do primeiro WITH/SELECT em diante.
    Remove o `;` final para facilitar compor a consulta depois (ex.: envolver em LIMIT).
    """
    match = _CODE_BLOCK.search(text)
    candidate = match.group(1) if match else ""
    if not candidate.strip():
        bare = _BARE_QUERY.search(text)
        candidate = bare.group(0) if bare else ""

    sql = candidate.strip().rstrip(";").strip()
    if not sql:
        raise ValueError(f"Não encontrei SQL na resposta do modelo:\n{text}")
    return sql
