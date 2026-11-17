"""Pergunte ao agente pelo terminal.

Uso:
  uv run python scripts/chat.py "Quantos pedidos foram entregues?"   # uma pergunta
  uv run python scripts/chat.py                                      # modo interativo
"""

import sys

from textsql.agent import Agent, AgentResult, build_agent
from textsql.errors import LLMError

MAX_ROWS_SHOWN = 20

LABELS = {
    "ok": "Resposta",
    "unanswerable": "Sem consulta",
    "blocked": "Bloqueado",
    "failed": "Falhou",
}


def show(result: AgentResult) -> None:
    for i, attempt in enumerate(result.attempts, 1):
        if attempt.error:
            print(f"\n[tentativa {i}] {attempt.error.splitlines()[0]}")

    if result.sql:
        print(f"\nSQL:\n{result.sql}\n")

    if result.rows is not None:
        total = len(result.rows)
        limit_note = " - limite atingido, há mais linhas" if result.truncated else ""
        print(f"Resultado ({total} linha(s){limit_note}):")
        if total:
            print(result.rows.head(MAX_ROWS_SHOWN).to_string(index=False))
            if total > MAX_ROWS_SHOWN:
                print(f"... (+{total - MAX_ROWS_SHOWN} linhas)")

    print(f"\n{LABELS[result.status]}: {result.answer.strip()}")
    if result.trace:
        t = result.trace
        print(
            f"[{t.duration_ms / 1000:.1f}s · {t.llm_calls} chamada(s) ao LLM · "
            f"{t.tokens} tokens · trace {t.trace_id}]"
        )
    print()


def ask(agent: Agent, question: str, history: list[AgentResult]) -> None:
    try:
        result = agent.ask(question, history)
    except LLMError as exc:
        print(f"\nErro ao chamar o LLM: {exc}\n")
        return
    show(result)
    history.append(result)


def main() -> int:
    # no Windows, saída redirecionada (pipe, arquivo) usaria cp1252 e quebraria acentos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        agent = build_agent()
    except (ValueError, FileNotFoundError) as exc:  # chave ausente, banco não gerado
        print(exc)
        return 1

    history: list[AgentResult] = []  # memória da conversa no modo interativo
    if len(sys.argv) > 1:
        ask(agent, " ".join(sys.argv[1:]), history)
        return 0

    print("Pergunte sobre os dados da Olist (ou 'sair'). Pode fazer perguntas de seguimento.")
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question.lower() in {"sair", "exit", "quit", ""}:
            break
        ask(agent, question, history)
    return 0


if __name__ == "__main__":
    sys.exit(main())
