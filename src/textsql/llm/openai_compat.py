"""Cliente para qualquer API compatível com OpenAI (Groq, OpenRouter, Ollama, ...).

Esses provedores expõem o mesmo endpoint `/chat/completions`; o que muda é só
`base_url`, chave e nome do modelo. Por isso um único cliente atende todos.
"""

from __future__ import annotations

from openai import OpenAI

from textsql.llm.base import Message


class OpenAICompatibleClient:
    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        self.model = model
        self.base_url = base_url
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]  # dicts simples são aceitos em runtime
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
