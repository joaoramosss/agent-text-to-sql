"""Baixa o Olist (se necessário) e carrega no DuckDB.

Uso:
  uv run python scripts/load_data.py                 # baixa do Kaggle via kagglehub (sem conta)
  uv run python scripts/load_data.py --source data/raw   # usa CSVs já baixados
"""

import argparse
import sys
import time
from pathlib import Path

from textsql.config import load_settings
from textsql.load import download_olist, load_olist


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="pasta com os CSVs (padrão: baixa do Kaggle)")
    parser.add_argument(
        "--db", type=Path, help="arquivo .duckdb de saída (padrão: DB_PATH do .env)"
    )
    args = parser.parse_args()

    source = args.source or download_olist()
    db_path = args.db or load_settings().db_path

    start = time.perf_counter()
    try:
        counts = load_olist(source, db_path)
    except FileNotFoundError as exc:
        print(exc)
        return 1

    width = max(len(t) for t in counts)
    for table, n in counts.items():
        print(f"  {table:<{width}}  {n:>9,}")
    print(f"\n{len(counts)} tabelas em {db_path} ({time.perf_counter() - start:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
