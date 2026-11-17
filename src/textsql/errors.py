"""Exceções do projeto.

A divisão que importa para o agente é *quem pode resolver o problema*:

- `SQLError`: o próprio LLM pode corrigir (sintaxe, tabela/coluna inexistente, timeout).
  A mensagem volta para o modelo e ele tenta de novo.
- `UnsafeSQLError`: bloqueio de segurança. Nunca volta para o modelo; o agente para na hora,
  para não ficar "negociando" com ele um jeito de passar pelo guardrail.
- `LLMError`: falha de infraestrutura (rede, cota, provedor fora do ar). Não é culpa do SQL.
"""


class TextSQLError(Exception):
    """Base de todas as exceções do projeto."""


class SQLError(TextSQLError):
    """SQL que o LLM pode corrigir. A mensagem é enviada de volta ao modelo."""


class QueryTimeoutError(SQLError):
    """A consulta passou do tempo limite (em geral, JOIN sem condição)."""


class UnsafeSQLError(TextSQLError):
    """SQL bloqueado pelos guardrails. Não é reenviado ao modelo."""


class LLMError(TextSQLError):
    """Falha ao chamar o provedor de LLM (rede, limite de requisições, erro do servidor)."""
