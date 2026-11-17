"""Cliente para qualquer API compatível com OpenAI (Groq, OpenRouter, Ollama, ...).

Esses provedores expõem o mesmo endpoint `/chat/completions`; o que muda é só
`base_url`, chave e nome do modelo. Por isso um único cliente atende todos.
"""

from __future__ import annotations

import threading

import openai
from openai import OpenAI

from textsql.errors import LLMError
from textsql.llm.base import Message


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        max_retries: int = 2,
    ):
        self.model = model
        self.base_url = base_url
        # o SDK já repete sozinho, com espera crescente, em erro de rede, 429 e 5xx
        self._client = OpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout, max_retries=max_retries
        )
        # consumo da última chamada, por thread: o mesmo cliente atende várias sessões
        self._local = threading.local()

    @property
    def last_usage(self) -> dict[str, int] | None:
        """Tokens da última chamada feita *nesta thread* (None se o provedor não informou)."""
        return getattr(self._local, "usage", None)

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]  # dicts simples são aceitos em runtime
                temperature=temperature,
            )
        except openai.APIError as exc:
            # traduz para um erro do projeto: o agente não precisa conhecer o SDK da OpenAI
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        usage = response.usage
        self._local.usage = (
            {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }
            if usage
            else None
        )
        return response.choices[0].message.content or ""
