"""Configuração do projeto, lida do `.env`.

Regra: segredos e escolhas de ambiente ficam em variáveis de ambiente;
o código nunca contém chaves. `Settings` é o único lugar que sabe os nomes das variáveis.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]

Provider = Literal["groq", "openrouter"]


class Settings(BaseModel):
    llm_provider: Provider = "groq"
    llm_model: str = "openai/gpt-oss-120b"
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    db_path: Path = PROJECT_ROOT / "data" / "olist.duckdb"


# Variável de ambiente -> campo de Settings. O teste garante que o .env.example documenta todas.
ENV_VARS: dict[str, str] = {
    "LLM_PROVIDER": "llm_provider",
    "LLM_MODEL": "llm_model",
    "GROQ_API_KEY": "groq_api_key",
    "OPENROUTER_API_KEY": "openrouter_api_key",
    "DB_PATH": "db_path",
}


def load_settings(env_file: Path | None = None) -> Settings:
    """Carrega o `.env` (se existir) e monta Settings a partir do ambiente.

    Variáveis já definidas no ambiente têm prioridade sobre o arquivo.
    Valores vazios no .env ("GROQ_API_KEY=") são tratados como ausentes.
    """
    load_dotenv(env_file or PROJECT_ROOT / ".env")
    values = {field: os.getenv(var) for var, field in ENV_VARS.items()}
    values = {k: v for k, v in values.items() if v}  # descarta None e ""
    if "llm_provider" in values:
        values["llm_provider"] = values["llm_provider"].lower()
    return Settings(**values)
