"""Configuração do projeto, lida do `.env`.

Regra: segredos e escolhas de ambiente ficam em variáveis de ambiente;
o código nunca contém chaves. `Settings` é o único lugar que sabe os nomes das variáveis.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, PositiveFloat, PositiveInt

PROJECT_ROOT = Path(__file__).resolve().parents[2]

Provider = Literal["groq", "openrouter"]


class Settings(BaseModel):
    llm_provider: Provider = "groq"
    llm_model: str = "openai/gpt-oss-120b"
    groq_api_key: str | None = None
    openrouter_api_key: str | None = None
    db_path: Path = PROJECT_ROOT / "data" / "olist.duckdb"
    # limites do agente
    sql_max_rows: PositiveInt = 1000
    sql_timeout_seconds: PositiveFloat = 10.0
    agent_max_attempts: PositiveInt = 3
    # observabilidade: arquivo JSONL com um trace por pergunta (None = desligado)
    trace_file: Path | None = PROJECT_ROOT / "logs" / "traces.jsonl"


# Variável de ambiente -> campo de Settings. O teste garante que o .env.example documenta todas.
ENV_VARS: dict[str, str] = {
    "LLM_PROVIDER": "llm_provider",
    "LLM_MODEL": "llm_model",
    "GROQ_API_KEY": "groq_api_key",
    "OPENROUTER_API_KEY": "openrouter_api_key",
    "DB_PATH": "db_path",
    "SQL_MAX_ROWS": "sql_max_rows",
    "SQL_TIMEOUT_SECONDS": "sql_timeout_seconds",
    "AGENT_MAX_ATTEMPTS": "agent_max_attempts",
    "TRACE_FILE": "trace_file",
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
    if values.get("trace_file", "").lower() == "off":
        values["trace_file"] = None
    return Settings(**values)
