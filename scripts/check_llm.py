"""Smoke test: confirma que o .env está certo e que o provedor responde.

Uso: uv run python scripts/check_llm.py
"""

import sys
import time

from textsql.config import load_settings
from textsql.llm import get_llm


def main() -> int:
    settings = load_settings()
    try:
        llm = get_llm(settings)
    except ValueError as exc:
        print(f"Config inválida: {exc}")
        return 1

    print(f"provedor: {settings.llm_provider}  modelo: {llm.model}")
    start = time.perf_counter()
    answer = llm.complete(
        [
            {"role": "system", "content": "Responda em português, em uma frase."},
            {"role": "user", "content": "Diga 'OK' e o nome do seu modelo."},
        ]
    )
    elapsed = time.perf_counter() - start
    print(f"resposta ({elapsed:.2f}s): {answer.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
