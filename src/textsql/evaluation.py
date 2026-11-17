"""Avaliação do agente: compara o resultado do SQL gerado com o de um SQL de referência.

Por que comparar resultados e não o texto do SQL: a mesma pergunta tem muitos SQLs corretos
(JOIN ou subconsulta, CTE ou não, aliases diferentes). O que importa é a resposta. É a métrica
"execution accuracy" usada em benchmarks de text-to-SQL (Spider, BIRD), aqui um pouco mais
tolerante:

- nomes de coluna são ignorados, e colunas extras do agente são aceitas;
- a ordem das linhas só conta quando a pergunta pede ordem (`ordered`);
- números são comparados com tolerância (0,1% ou 0,01), pois o agente pode arredondar diferente;
- textos sem diferença de maiúsculas/espaços; datas pelo valor.
"""

from __future__ import annotations

import datetime as dt
import itertools
import math
import time
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from textsql.agent import Agent
from textsql.db import Database
from textsql.errors import LLMError

REL_TOL = 1e-3
ABS_TOL = 0.011  # 4.0864 deve bater com 4.09 (a referência arredondou para 2 casas)
MAX_COLUMN_MAPPINGS = 5000


# --- conjunto de perguntas ----------------------------------------------------------------------


@dataclass
class EvalQuestion:
    id: str
    category: str
    question: str
    sql: list[str] = field(default_factory=list)  # referências aceitas (vazia = recusa)
    ordered: bool = False
    expect: str = "answer"  # "answer" | "refusal"


def load_questions(path: Path) -> list[EvalQuestion]:
    with open(path, "rb") as f:
        raw = tomllib.load(f)["question"]
    questions = []
    for item in raw:
        sql = item.get("sql", [])
        questions.append(
            EvalQuestion(
                id=item["id"],
                category=item["category"],
                question=item["question"],
                sql=[sql] if isinstance(sql, str) else list(sql),
                ordered=item.get("ordered", False),
                expect=item.get("expect", "answer"),
            )
        )
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("ids repetidos no conjunto de avaliação")
    for q in questions:
        if q.expect == "answer" and not q.sql:
            raise ValueError(f"{q.id}: pergunta sem SQL de referência")
    return questions


# --- comparação de resultados -------------------------------------------------------------------


def results_match(expected: pd.DataFrame, actual: pd.DataFrame, *, ordered: bool) -> bool:
    """O resultado do agente contém o da referência?

    Cada coluna esperada precisa corresponder a uma coluna diferente do agente (pelo conteúdo,
    não pelo nome); depois, as linhas são comparadas inteiras, para não aceitar colunas certas
    "desalinhadas" entre si.
    """
    if len(expected) != len(actual) or len(expected.columns) > len(actual.columns):
        return False
    exp_cols = [_column(expected, i) for i in range(len(expected.columns))]
    act_cols = [_column(actual, i) for i in range(len(actual.columns))]

    # candidatas: colunas do agente com os mesmos valores (ignorando a ordem das linhas)
    act_sorted = [sorted_values(act) for act in act_cols]
    candidates = []
    for exp in exp_cols:
        exp_sorted = sorted_values(exp)
        matches = [j for j, act in enumerate(act_sorted) if _same_values(exp_sorted, act)]
        if not matches:
            return False
        candidates.append(matches)

    expected_rows = list(zip(*exp_cols, strict=True)) if exp_cols else []
    for mapping in itertools.islice(itertools.product(*candidates), MAX_COLUMN_MAPPINGS):
        if len(set(mapping)) != len(mapping):  # duas colunas esperadas na mesma coluna do agente
            continue
        actual_rows = list(zip(*(act_cols[j] for j in mapping), strict=True))
        if _same_rows(expected_rows, actual_rows, ordered=ordered):
            return True
    return False


def normalize(value: Any) -> Any:
    """Leva valores de tipos diferentes a uma forma comparável."""
    if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NaT:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float | Decimal) or hasattr(value, "dtype"):  # numpy também
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    if isinstance(value, pd.Timestamp | dt.datetime):
        ts = pd.Timestamp(value)
        return ts.date().isoformat() if ts == ts.normalize() else ts.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value).strip().lower()


def sorted_values(values: Sequence[Any]) -> list[Any]:
    return sorted(values, key=_sort_key)


def _column(df: pd.DataFrame, i: int) -> list[Any]:
    return [normalize(v) for v in df.iloc[:, i].tolist()]


def _sort_key(value: Any) -> tuple:
    if value is None:
        return (0, "")
    if isinstance(value, float):
        return (1, round(value, 2))
    return (2, str(value))


def _row_key(row: tuple) -> tuple:
    return tuple(_sort_key(v) for v in row)


def _equal(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)
    return a == b


def _same_values(a: list[Any], b: list[Any]) -> bool:
    return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b, strict=True))


def _same_rows(expected: list[tuple], actual: list[tuple], *, ordered: bool) -> bool:
    if not ordered:
        expected, actual = sorted(expected, key=_row_key), sorted(actual, key=_row_key)
    return all(
        all(_equal(x, y) for x, y in zip(e, a, strict=True))
        for e, a in zip(expected, actual, strict=True)
    )


# --- execução da avaliação ----------------------------------------------------------------------


@dataclass
class EvalRecord:
    id: str
    category: str
    question: str
    expect: str
    status: str  # status do AgentResult, ou "llm_error"
    correct: bool
    attempts: int
    first_try: bool  # acertou sem precisar de autocorreção
    latency_s: float
    sql: str | None
    error: str | None = None
    tokens: int = 0
    trace_id: str | None = None  # liga o registro ao trace completo em logs/traces.jsonl

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_question(
    agent: Agent,
    db: Database,
    q: EvalQuestion,
    *,
    llm_retries: int = 3,
    retry_wait_s: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> EvalRecord:
    """Roda uma pergunta. Erro do LLM (ex.: limite de tokens por minuto) espera e tenta de novo."""
    start = time.perf_counter()
    for retry in range(llm_retries + 1):
        try:
            result = agent.ask(q.question, explain=False)
            break
        except LLMError as exc:
            if retry == llm_retries:
                return EvalRecord(
                    id=q.id,
                    category=q.category,
                    question=q.question,
                    expect=q.expect,
                    status="llm_error",
                    correct=False,
                    attempts=0,
                    first_try=False,
                    latency_s=round(time.perf_counter() - start, 2),
                    sql=None,
                    error=str(exc),
                )
            sleep(retry_wait_s)
    latency = time.perf_counter() - start

    if q.expect == "refusal":
        correct = result.status in ("unanswerable", "blocked")
    else:
        correct = result.status == "ok" and any(
            results_match(db.query(ref), result.rows, ordered=q.ordered) for ref in q.sql
        )
    last_error = next((a.error for a in reversed(result.attempts) if a.error), None)
    return EvalRecord(
        id=q.id,
        category=q.category,
        question=q.question,
        expect=q.expect,
        status=result.status,
        correct=correct,
        attempts=len(result.attempts),
        first_try=correct and len(result.attempts) <= 1,
        latency_s=round(latency, 2),
        sql=result.sql,
        error=last_error if not correct else None,
        tokens=result.trace.tokens if result.trace else 0,
        trace_id=result.trace.trace_id if result.trace else None,
    )


def summarize(records: Sequence[EvalRecord]) -> dict[str, Any]:
    total = len(records)
    correct = sum(r.correct for r in records)
    by_category: dict[str, list[int]] = {}
    for r in records:
        hits = by_category.setdefault(r.category, [0, 0])
        hits[0] += r.correct
        hits[1] += 1
    return {
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "first_try": sum(r.first_try for r in records),
        "fixed_by_retry": sum(r.correct and r.attempts > 1 for r in records),
        "llm_errors": sum(r.status == "llm_error" for r in records),
        "avg_latency_s": round(sum(r.latency_s for r in records) / total, 2) if total else 0.0,
        "avg_tokens": round(sum(r.tokens for r in records) / total) if total else 0,
        "by_category": {k: {"correct": v[0], "total": v[1]} for k, v in by_category.items()},
    }


def report_markdown(records: Sequence[EvalRecord], summary: dict[str, Any], model: str) -> str:
    pct = f"{summary['accuracy']:.0%}"
    lines = [
        f"# Avaliação — {model}",
        "",
        f"**Acerto: {summary['correct']}/{summary['total']} ({pct})** · "
        f"de primeira: {summary['first_try']} · corrigidas pela autocorreção: "
        f"{summary['fixed_by_retry']} · erros do provedor: {summary['llm_errors']} · "
        f"latência média: {summary['avg_latency_s']}s · tokens por pergunta: "
        f"{summary['avg_tokens']}",
        "",
        "| Categoria | Acerto |",
        "|---|---|",
    ]
    for cat, v in summary["by_category"].items():
        lines.append(f"| {cat} | {v['correct']}/{v['total']} |")
    lines += [
        "",
        "| id | status | ok | tentativas | s | tokens |",
        "|---|---|---|---|---|---|",
    ]
    for r in records:
        mark = "✅" if r.correct else "❌"
        lines.append(
            f"| {r.id} | {r.status} | {mark} | {r.attempts} | {r.latency_s} | {r.tokens} |"
        )
    failures = [r for r in records if not r.correct]
    if failures:
        lines += ["", "## Erros", ""]
        for r in failures:
            lines += [f"### {r.id}", f"> {r.question}", ""]
            if r.sql:
                lines += ["```sql", r.sql, "```"]
            if r.error:
                lines.append(f"Erro: `{r.error.splitlines()[0]}`")
            lines.append("")
    return "\n".join(lines) + "\n"
