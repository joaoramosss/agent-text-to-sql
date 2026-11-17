"""Fábrica de clientes de LLM. Uso: `llm = get_llm()`."""

from __future__ import annotations

from textsql.config import Settings, load_settings
from textsql.llm.base import LLMClient, Message
from textsql.llm.openai_compat import OpenAICompatibleClient

__all__ = ["LLMClient", "Message", "get_llm", "PROVIDERS"]

# provedor -> (base_url, campo de Settings com a chave)
PROVIDERS: dict[str, tuple[str, str]] = {
    "groq": ("https://api.groq.com/openai/v1", "groq_api_key"),
    "openrouter": ("https://openrouter.ai/api/v1", "openrouter_api_key"),
}


def get_llm(settings: Settings | None = None) -> LLMClient:
    """Monta o cliente conforme LLM_PROVIDER / LLM_MODEL. Falha cedo se faltar a chave."""
    settings = settings or load_settings()
    provider = settings.llm_provider

    if provider not in PROVIDERS:
        raise ValueError(f"LLM_PROVIDER='{provider}' desconhecido. Opções: {', '.join(PROVIDERS)}")

    base_url, key_field = PROVIDERS[provider]
    api_key = getattr(settings, key_field)
    if not api_key:
        raise ValueError(f"Defina {key_field.upper()} no .env para usar o provedor '{provider}'")

    return OpenAICompatibleClient(base_url=base_url, api_key=api_key, model=settings.llm_model)
