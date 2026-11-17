"""Como mostrar um resultado: escolha do gráfico e ajustes de texto.

Puro pandas, sem Streamlit: a interface só desenha o que `suggest_chart` decide, e a regra
de escolha fica testável. A regra segue o "trabalho" dos dados:

- 1 linha            -> números em destaque (metric), não um gráfico de uma barra só
- tempo + número     -> linha (tendência)
- categoria + número -> barras horizontais, na ordem que o SQL devolveu (ranking)
- qualquer outra     -> sem gráfico; a tabela aparece sempre
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import pandas as pd

MAX_BARS = 30  # mais do que isso vira parede de barras; fica só a tabela
MAX_METRICS = 4

_PERIOD_TEXT = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")  # '2018-01' ou '2018-01-15'
_TIME_NAME = re.compile(r"(^|_)(ano|mes|mês|dia|semana|year|month|day|week|data|date)($|_)")


@dataclass
class ChartSpec:
    kind: Literal["metric", "line", "bar"]
    x: str | None = None
    y: str | None = None  # uma medida só: dois eixos Y no mesmo gráfico confundem
    metrics: tuple[str, ...] = ()


def suggest_chart(df: pd.DataFrame) -> ChartSpec | None:
    if df.empty:
        return None

    numeric = [c for c in df.columns if _is_number(df[c])]
    if len(df) == 1:
        return ChartSpec("metric", metrics=tuple(numeric[:MAX_METRICS])) if numeric else None

    time_col = next((c for c in df.columns if _is_time(df[c])), None)
    measures = [c for c in numeric if c != time_col]
    if time_col and measures:
        return ChartSpec("line", x=time_col, y=measures[0])

    labels = [c for c in df.columns if c not in numeric]
    if labels and measures and len(df) <= MAX_BARS and df[labels[0]].is_unique:
        return ChartSpec("bar", x=labels[0], y=measures[0])
    return None


def as_time(series: pd.Series) -> pd.Series:
    """Converte a coluna de tempo para datetime (texto '2018-01' vira 2018-01-01)."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    if pd.api.types.is_numeric_dtype(series):  # ano/mês como número: fica como está
        return series
    return pd.to_datetime(series.astype(str), format="mixed")


def format_number(value: float) -> str:
    """Formato brasileiro: 96478 -> '96.478'; 1234.5 -> '1.234,50'."""
    if pd.isna(value):
        return "—"
    text = f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def escape_markdown(text: str) -> str:
    """No Streamlit, texto entre dois `$` vira fórmula LaTeX: "R$ 10 e R$ 20" quebraria."""
    return text.replace("$", r"\$")


def _is_number(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)


def _is_time(s: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(s):
        return True
    name = str(s.name).lower()
    if pd.api.types.is_integer_dtype(s):  # ex.: coluna "ano" com 2016, 2017, 2018
        return bool(_TIME_NAME.search(name))
    if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
        values = s.dropna().astype(str)
        return len(values) > 0 and bool(values.map(lambda v: bool(_PERIOD_TEXT.match(v))).all())
    return False
