"""Pergunte ao agente pelo terminal.

Uso:
  uv run python scripts/chat.py "Quantos pedidos foram entregues?"   # uma pergunta
  uv run python scripts/chat.py                                      # modo interativo
"""

import sys

import duckdb

from textsql.agent import Agent, AgentResult
from textsql.db import Database
from textsql.llm import get_llm

MAX_ROWS_SHOWN = 20


def show(result: AgentResult) -> None:
    print(f"\nSQL:\n{result.sql}\n")
    total = len(result.rows)
    print(f"Resultado ({total} linha(s)):")
    if total:
        print(result.rows.head(MAX_ROWS_SHOWN).to_string(index=False))
        if total > MAX_ROWS_SHOWN:
            print(f"... (+{total - MAX_ROWS_SHOWN} linhas)")
    print(f"\nResposta: {result.answer.strip()}\n")


def ask(agent: Agent, question: str) -> None:
    try:
        show(agent.ask(question))
    except duckdb.Error as exc:
        print(f"\nErro ao executar o SQL: {exc}\n")
    except ValueError as exc:
        print(f"\n{exc}\n")


def main() -> int:
    agent = Agent(get_llm(), Database())

    if len(sys.argv) > 1:
        ask(agent, " ".join(sys.argv[1:]))
        return 0

    print("Pergunte sobre os dados da Olist (ou 'sair').")
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question.lower() in {"sair", "exit", "quit", ""}:
            break
        ask(agent, question)
    return 0


if __name__ == "__main__":
    sys.exit(main())
