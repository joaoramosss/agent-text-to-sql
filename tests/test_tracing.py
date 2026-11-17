import json
import threading

import pytest
from conftest import FakeLLM

from textsql.agent import Agent
from textsql.errors import LLMError
from textsql.tracing import (
    MAX_TEXT,
    JsonlTraceSink,
    Trace,
    emit_safely,
    read_traces,
    summarize_traces,
)

COUNT = "```sql\nSELECT count(*) AS n FROM orders\n```"


class ListSink:
    def __init__(self):
        self.traces = []

    def emit(self, trace):
        self.traces.append(trace)


class BrokenSink:
    def emit(self, trace):
        raise OSError("disco cheio")


# --- Trace e Span -------------------------------------------------------------------------------


def test_span_mede_tempo_e_guarda_atributos():
    trace = Trace("q")
    with trace.span("execute", attempt=2) as span:
        span.set(rows=10, ignorado=None)
    [span] = trace.spans
    assert span.name == "execute" and span.attempt == 2
    assert span.duration_ms >= 0 and span.status == "ok"
    assert span.attrs == {"rows": 10}


def test_span_registra_erro_e_repassa_a_excecao():
    trace = Trace("q")
    with pytest.raises(ValueError), trace.span("validate"):
        raise ValueError("SQL vazio")
    assert trace.spans[0].status == "error"
    assert trace.spans[0].error == "ValueError: SQL vazio"


def test_textos_longos_sao_cortados():
    trace = Trace("q")
    with trace.span("generate_sql") as span:
        span.set(output="x" * (MAX_TEXT + 100))
    assert len(trace.spans[0].attrs["output"]) == MAX_TEXT


def test_totais_e_serializacao():
    trace = Trace("q", model="m", prompt_version="abc")
    for name, tokens in [("generate_sql", 100), ("validate", None), ("answer", 30)]:
        with trace.span(name) as span:
            span.set(total_tokens=tokens)
    trace.finish("ok")

    assert trace.tokens == 130 and trace.llm_calls == 2
    data = json.loads(json.dumps(trace.to_dict()))
    assert data["status"] == "ok" and data["prompt_version"] == "abc"
    assert [s["name"] for s in data["spans"]] == ["generate_sql", "validate", "answer"]
    assert "llm_calls=2 tokens=130" in trace.summary()


# --- sinks --------------------------------------------------------------------------------------


def test_jsonl_uma_linha_por_trace_mesmo_com_threads(tmp_path):
    sink = JsonlTraceSink(tmp_path / "logs" / "traces.jsonl")
    traces = [Trace(f"pergunta {i}") for i in range(20)]
    threads = [threading.Thread(target=sink.emit, args=(t,)) for t in traces]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = read_traces(sink.path)
    assert sorted(t["question"] for t in lines) == sorted(t.question for t in traces)


def test_falha_num_sink_nao_impede_os_outros():
    good = ListSink()
    emit_safely(Trace("q"), [BrokenSink(), good])
    assert len(good.traces) == 1


def test_read_traces_pula_linha_corrompida(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text('{"trace_id": "a"}\n{"trace_id": "b", "spa\n', encoding="utf-8")
    assert [t["trace_id"] for t in read_traces(path)] == ["a"]
    assert read_traces(tmp_path / "nao_existe.jsonl") == []


def test_resumo_dos_traces():
    def fake(status, ms, spans, tokens=100):
        return {
            "status": status,
            "duration_ms": ms,
            "tokens": tokens,
            "spans": [{"name": n, "duration_ms": d, "error": e} for n, d, e in spans],
        }

    traces = [
        fake("ok", 1000, [("generate_sql", 800, None), ("execute", 50, None)]),
        fake(
            "ok",
            3000,
            [
                ("generate_sql", 900, None),
                ("execute", 40, "SQLError: Binder Error: coluna x"),
                ("generate_sql", 950, None),
                ("execute", 60, None),
            ],
        ),
        fake(
            "blocked", 500, [("generate_sql", 400, None), ("validate", 1, "UnsafeSQLError: DROP")]
        ),
    ]
    s = summarize_traces(traces)

    assert s["total"] == 3 and s["by_status"] == {"ok": 2, "blocked": 1}
    assert s["retry_rate"] == round(1 / 3, 3)
    assert s["avg_tokens"] == 100 and s["total_tokens"] == 300
    assert s["per_span"]["generate_sql"]["count"] == 4
    assert s["per_span"]["execute"]["error_rate"] == round(1 / 3, 3)
    assert ("SQLError: Binder Error: coluna x", 1) in s["top_errors"]


def test_resumo_vazio():
    assert summarize_traces([]) == {"total": 0}


# --- integração com o agente --------------------------------------------------------------------


def test_trace_do_caminho_feliz(mini_db):
    sink = ListSink()
    llm = FakeLLM(COUNT, "Há 2 pedidos.", tokens_per_call=50)
    result = Agent(llm, mini_db, trace_sinks=[sink]).ask("Quantos pedidos?")

    trace = result.trace
    assert sink.traces == [trace]
    assert trace.status == "ok" and trace.model == "fake" and len(trace.prompt_version) == 10
    assert [s.name for s in trace.spans] == ["generate_sql", "validate", "execute", "answer"]
    gen, val, exe, ans = trace.spans
    assert gen.attrs["input"] == "Quantos pedidos?" and gen.attrs["output"] == COUNT
    assert val.attrs["sql"] == "SELECT count(*) AS n FROM orders"
    assert exe.attrs == {"rows": 1, "truncated": False}
    assert ans.attrs["output"] == "Há 2 pedidos."
    assert trace.tokens == 100 and trace.llm_calls == 2


def test_trace_mostra_a_autocorrecao(mini_db):
    llm = FakeLLM("```sql\nSELECT nope FROM orders\n```", COUNT, "ok")
    trace = Agent(llm, mini_db).ask("x").trace

    steps = [(s.name, s.attempt, s.status) for s in trace.spans]
    assert steps == [
        ("generate_sql", 1, "ok"),
        ("validate", 1, "ok"),
        ("execute", 1, "error"),
        ("generate_sql", 2, "ok"),
        ("validate", 2, "ok"),
        ("execute", 2, "ok"),
        ("answer", None, "ok"),
    ]
    assert "nope" in trace.spans[2].error
    assert "nope" in trace.spans[3].attrs["input"]  # o erro foi a entrada da 2ª geração


def test_trace_de_bloqueio_e_fora_do_escopo(mini_db):
    blocked = Agent(FakeLLM("```sql\nDROP TABLE orders\n```"), mini_db).ask("x").trace
    assert blocked.status == "blocked"
    assert blocked.spans[-1].name == "validate" and "UnsafeSQLError" in blocked.spans[-1].error

    out = Agent(FakeLLM("SEM_SQL: sem dados de clima."), mini_db).ask("x").trace
    assert out.status == "unanswerable" and [s.name for s in out.spans] == ["generate_sql"]


def test_avaliacao_sem_explicacao_nao_tem_span_answer(mini_db):
    trace = Agent(FakeLLM(COUNT), mini_db).ask("x", explain=False).trace
    assert "answer" not in [s.name for s in trace.spans]


class DownLLM(FakeLLM):
    def complete(self, messages, *, temperature=0.0):
        raise LLMError("APIConnectionError: sem rede")


def test_falha_do_llm_ainda_gera_trace(mini_db):
    sink = ListSink()
    with pytest.raises(LLMError):
        Agent(DownLLM(), mini_db, trace_sinks=[sink]).ask("x")

    [trace] = sink.traces
    assert trace.status == "llm_error"
    assert trace.spans[0].name == "generate_sql" and "sem rede" in trace.spans[0].error


def test_sink_quebrado_nao_derruba_o_agente(mini_db):
    result = Agent(FakeLLM(COUNT, "ok"), mini_db, trace_sinks=[BrokenSink()]).ask("x")
    assert result.ok
