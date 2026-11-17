"""Resumo dos traces gravados pelo agente (logs/traces.jsonl).

Uso:
  uv run python scripts/traces.py              # todos os traces
  uv run python scripts/traces.py --last 50    # só os 50 mais recentes
  uv run python scripts/traces.py --show ID    # um trace completo, etapa por etapa
"""

import argparse
import json
import sys

from textsql.config import load_settings
from textsql.tracing import read_traces, summarize_traces


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--last", type=int, help="considera só os N traces mais recentes")
    parser.add_argument("--show", metavar="ID", help="mostra um trace completo")
    args = parser.parse_args()

    path = load_settings().trace_file
    traces = read_traces(path) if path else []
    if not traces:
        print(f"Nenhum trace em {path}. Faça perguntas pelo chat, app ou avaliação.")
        return 1

    if args.show:
        match = [t for t in traces if t["trace_id"] == args.show]
        if not match:
            print(f"Trace {args.show} não encontrado.")
            return 1
        print(json.dumps(match[0], ensure_ascii=False, indent=2))
        return 0

    if args.last:
        traces = traces[-args.last :]
    s = summarize_traces(traces)
    print(f"{s['total']} perguntas  ·  status: {s['by_status']}")
    print(f"latência total: p50 {s['p50_ms']} ms · p95 {s['p95_ms']} ms")
    print(f"perguntas com nova tentativa: {s['retry_rate']:.0%}")
    print(f"tokens: {s['avg_tokens']} por pergunta · {s['total_tokens']} no total\n")

    print(f"{'etapa':<14}{'qtd':>6}{'p50 ms':>9}{'p95 ms':>9}{'erros':>8}")
    for name, v in s["per_span"].items():
        print(f"{name:<14}{v['count']:>6}{v['p50_ms']:>9}{v['p95_ms']:>9}{v['error_rate']:>8.0%}")

    if s["top_errors"]:
        print("\nerros mais comuns:")
        for message, count in s["top_errors"]:
            print(f"  {count:>3}x  {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
