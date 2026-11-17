"""Textos de prompt ficam em arquivos .md nesta pasta, não em strings no código."""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
