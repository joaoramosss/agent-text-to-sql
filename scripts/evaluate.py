"""Mede a taxa de acerto do agente no conjunto `eval/questions.toml`.

Uso:
  uv run python scripts/evaluate.py                          # todas as perguntas
  uv run python scripts/evaluate.py --only ticket_medio,vendedores
  uv run python scripts/evaluate.py --category ranking

Grava em eval/results/: <data>_<modelo>.jsonl (um registro por pergunta) e .md (relatório).
O free tier da Groq limita tokens por minuto: há uma pausa entre perguntas e, se o provedor
recusar, a pergunta espera e tenta de novo.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime

from textsql.agent import build_agent
from textsql.config import PROJECT_ROOT, load_settings
from textsql.evaluation import evaluate_question, load_questions, report_markdown, summarize

QUESTIONS = PROJECT_ROOT / "eval" / "questions.toml"
RESULTS = PROJECT_ROOT / "eval" / "results"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--only", help="ids separados por vírgula")
    parser.add_argument("--category", help="só uma categoria")
    parser.add_argument("--pause", type=float, default=8.0, help="segundos entre perguntas")
    args = parser.parse_args()

    questions = load_questions(QUESTIONS)
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q.id in wanted]
    if args.category:
        questions = [q for q in questions if q.category == args.category]
    if not questions:
        print("Nenhuma pergunta selecionada.")
        return 1

    settings = load_settings()
    agent = build_agent(settings)
    records = []
    for i, q in enumerate(questions, 1):
        if i > 1:
            time.sleep(args.pause)
        record = evaluate_question(agent, agent.db, q)
        records.append(record)
        mark = "OK " if record.correct else "ERR"
        print(
            f"[{i:>2}/{len(questions)}] {mark} {q.id:<32} {record.status:<12} "
            f"{record.attempts} tent.  {record.latency_s:>5.1f}s"
        )

    summary = summarize(records)
    RESULTS.mkdir(parents=True, exist_ok=True)
    model = re.sub(r"[^\w.-]+", "-", settings.llm_model)
    stem = RESULTS / f"{datetime.now():%Y-%m-%d_%H%M}_{model}"
    with open(stem.with_suffix(".jsonl"), "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
    stem.with_suffix(".md").write_text(
        report_markdown(records, summary, settings.llm_model), encoding="utf-8"
    )

    print(
        f"\nAcerto: {summary['correct']}/{summary['total']} ({summary['accuracy']:.0%})  "
        f"de primeira: {summary['first_try']}  corrigidas: {summary['fixed_by_retry']}  "
        f"erros do provedor: {summary['llm_errors']}"
    )
    for cat, v in summary["by_category"].items():
        print(f"  {cat:<10} {v['correct']}/{v['total']}")
    print(f"\nRelatório: {stem.with_suffix('.md').relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
