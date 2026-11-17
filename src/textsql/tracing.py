"""Tracing: o que aconteceu em cada etapa de uma pergunta, com tempo e tokens.

Cada `Agent.ask` gera um `Trace` (uma pergunta) com vários `Span`s (uma etapa cada):
`generate_sql`, `validate`, `execute` e `answer`; as três primeiras se repetem por tentativa.
O trace vai para os *sinks*: um arquivo JSONL (um trace por linha, fácil de analisar com
pandas/DuckDB) e uma linha de log (aparece no console e nos logs da hospedagem).

É o mesmo modelo de trace/span do OpenTelemetry, em ~150 linhas e sem dependência: para um
agente com 4 etapas, um coletor externo seria mais infraestrutura do que o problema pede.
Os nomes seguem o OTel, então trocar por ele depois é direto.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

logger = logging.getLogger("textsql")

LLM_SPANS = ("generate_sql", "answer")
MAX_TEXT = 4000  # textos longos (respostas do LLM, erros) são cortados no trace


@dataclass
class Span:
    name: str
    attempt: int | None = None
    start_ms: float = 0.0  # em relação ao início do trace
    duration_ms: float = 0.0
    status: str = "ok"  # "ok" | "error"
    error: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def set(self, **attrs: Any) -> None:
        for key, value in attrs.items():
            if value is None:
                continue
            self.attrs[key] = value[:MAX_TEXT] if isinstance(value, str) else value


@dataclass
class Trace:
    question: str
    model: str = ""
    prompt_version: str = ""  # hash do system prompt: diz qual versão do prompt foi usada
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    status: str = "running"
    duration_ms: float = 0.0
    spans: list[Span] = field(default_factory=list)
    _t0: float = field(default_factory=time.perf_counter, init=False, repr=False)

    @contextmanager
    def span(self, name: str, attempt: int | None = None) -> Iterator[Span]:
        """Mede um bloco. Se ele levantar exceção, o span registra o erro e a repassa."""
        span = Span(name, attempt, start_ms=self._elapsed_ms())
        self.spans.append(span)
        start = time.perf_counter()
        try:
            yield span
        except Exception as exc:
            span.status = "error"
            span.error = f"{type(exc).__name__}: {exc}"[:MAX_TEXT]
            raise
        finally:
            span.duration_ms = round((time.perf_counter() - start) * 1000, 1)

    def finish(self, status: str) -> None:
        self.status = status
        self.duration_ms = self._elapsed_ms()

    @property
    def tokens(self) -> int:
        return sum(s.attrs.get("total_tokens", 0) for s in self.spans)

    @property
    def llm_calls(self) -> int:
        return sum(s.name in LLM_SPANS for s in self.spans)

    def summary(self) -> str:
        """Uma linha, para log e terminal."""
        errors = sum(s.status == "error" for s in self.spans)
        return (
            f"trace={self.trace_id} status={self.status} total_ms={self.duration_ms:.0f} "
            f"llm_calls={self.llm_calls} tokens={self.tokens} span_errors={errors}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "started_at": self.started_at,
            "question": self.question,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "llm_calls": self.llm_calls,
            "tokens": self.tokens,
            "spans": [vars(s) for s in self.spans],
        }

    def _elapsed_ms(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 1)


# --- destinos dos traces ------------------------------------------------------------------------


class TraceSink(Protocol):
    def emit(self, trace: Trace) -> None: ...


class JsonlTraceSink:
    """Acrescenta um trace por linha num arquivo. O lock evita linhas misturadas entre threads."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def emit(self, trace: Trace) -> None:
        line = json.dumps(trace.to_dict(), ensure_ascii=False, default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")


class LoggingTraceSink:
    """Uma linha por pergunta no logger `textsql` (nível INFO)."""

    def emit(self, trace: Trace) -> None:
        logger.info(trace.summary())


def emit_safely(trace: Trace, sinks: list[TraceSink] | tuple[TraceSink, ...]) -> None:
    """Observabilidade não pode derrubar o produto: falha ao gravar vira só um aviso."""
    for sink in sinks:
        try:
            sink.emit(trace)
        except Exception:
            logger.warning("falha ao gravar trace em %s", type(sink).__name__, exc_info=True)


def summarize_traces(traces: list[dict[str, Any]], top_errors: int = 5) -> dict[str, Any]:
    """Números para acompanhar o agente: latência por etapa, retries, tokens e erros comuns."""
    if not traces:
        return {"total": 0}
    totals = pd.Series([t["duration_ms"] for t in traces])
    spans = pd.DataFrame(
        [
            {"name": s["name"], "ms": s["duration_ms"], "error": s["error"]}
            for t in traces
            for s in t["spans"]
        ]
    )
    per_span = {}
    if not spans.empty:
        for name, group in spans.groupby("name", sort=False):
            per_span[name] = {
                "count": len(group),
                "p50_ms": round(group["ms"].quantile(0.5)),
                "p95_ms": round(group["ms"].quantile(0.95)),
                "error_rate": round(group["error"].notna().mean(), 3),
            }
    generate_counts = [sum(s["name"] == "generate_sql" for s in t["spans"]) for t in traces]
    errors = Counter(
        s["error"].splitlines()[0][:120] for t in traces for s in t["spans"] if s["error"]
    )
    return {
        "total": len(traces),
        "by_status": dict(Counter(t["status"] for t in traces)),
        "p50_ms": round(totals.quantile(0.5)),
        "p95_ms": round(totals.quantile(0.95)),
        "retry_rate": round(sum(n > 1 for n in generate_counts) / len(traces), 3),
        "avg_tokens": round(sum(t["tokens"] for t in traces) / len(traces)),
        "total_tokens": sum(t["tokens"] for t in traces),
        "per_span": per_span,
        "top_errors": errors.most_common(top_errors),
    }


def read_traces(path: Path) -> list[dict[str, Any]]:
    """Lê o JSONL; linhas corrompidas (ex.: processo morto no meio da escrita) são puladas."""
    if not Path(path).exists():
        return []
    traces = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                traces.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return traces
