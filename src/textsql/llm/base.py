"""Contrato mínimo que o agente exige de um LLM.

O agente só precisa de uma coisa: mandar uma lista de mensagens e receber texto.
Qualquer provedor que cumpra isso pode ser trocado sem mexer no agente.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# {"role": "system" | "user" | "assistant", "content": "..."}
Message = dict[str, str]


@runtime_checkable
class LLMClient(Protocol):
    model: str

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> str:
        """Envia a conversa e devolve o texto da resposta do assistente.

        Falhas do provedor (rede, cota, erro do servidor) devem virar `textsql.errors.LLMError`.

        Opcional: um atributo `last_usage` ({"prompt_tokens", "completion_tokens",
        "total_tokens"}) com o consumo da última chamada; o tracing o registra se existir.
        """
        ...
