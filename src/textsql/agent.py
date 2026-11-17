"""O agente: pergunta -> SQL -> validação -> execução -> resposta, com autocorreção.

Fluxo de `ask`:
1. O LLM gera SQL (system prompt com o schema).
2. Os guardrails validam o SQL; o banco executa com limite de linhas e de tempo.
3. Erro corrigível (`SQLError`): a resposta do modelo e o erro entram na conversa e ele tenta
   de novo, até `max_attempts`. Bloqueio de segurança (`UnsafeSQLError`): para na hora.
4. Com o resultado, uma segunda chamada redige a resposta em português.

O agente não imprime nada: devolve um `AgentResult` com o status e o histórico de tentativas.
Falha de infraestrutura (`LLMError` ao gerar SQL) sobe como exceção: não é um "resultado".

Memória de conversa: o agente não guarda estado. Quem chama passa os resultados anteriores
(`history`) e o agente põe no prompt as últimas perguntas respondidas, com o SQL de cada uma.
Sem estado, um único agente atende várias sessões ao mesmo tempo (ex.: Streamlit).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from textsql.config import Settings, load_settings
from textsql.db import Database, QueryResult
from textsql.errors import LLMError, SQLError, UnsafeSQLError
from textsql.guardrails import validate_sql
from textsql.llm import LLMClient, Message, get_llm
from textsql.prompts import load_prompt
from textsql.schema import schema_description
from textsql.sql_utils import extract_sql, no_sql_reason

# ok: respondeu | unanswerable: o modelo disse que os dados não respondem isso |
# blocked: guardrail barrou | failed: esgotou as tentativas sem SQL válido
Status = Literal["ok", "unanswerable", "blocked", "failed"]

MAX_ERROR_CHARS = 1500  # erro devolvido ao modelo; os do DuckDB podem listar dezenas de colunas


@dataclass
class Attempt:
    sql: str  # vazio se o modelo não devolveu SQL
    error: str | None = None  # None = executou com sucesso


@dataclass
class AgentResult:
    question: str
    status: Status
    answer: str
    sql: str | None = None  # SQL da última tentativa
    rows: pd.DataFrame | None = None
    truncated: bool = False
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        db: Database,
        *,
        max_attempts: int = 3,
        max_rows: int = 1000,
        timeout_s: float = 10.0,
        sample_rows: int = 20,
        max_history: int = 3,
    ):
        self.llm = llm
        self.db = db
        self.max_attempts = max_attempts
        self.max_history = max_history
        self.max_rows = max_rows
        self.timeout_s = timeout_s
        self.sample_rows = sample_rows
        self.tables = db.tables()
        # o schema é estático: monta o system prompt uma vez só
        self._sql_system_prompt = load_prompt("generate_sql").replace(
            "{schema}", schema_description(db)
        )
        self._answer_system_prompt = load_prompt("answer")
        self._fix_prompt = load_prompt("fix_sql")

    def ask(
        self, question: str, history: Sequence[AgentResult] = (), *, explain: bool = True
    ) -> AgentResult:
        """Responde `question`. `history`: resultados anteriores da conversa, do mais antigo
        ao mais recente; permite perguntas de seguimento como "e por estado?".
        `explain=False` pula a chamada que redige a resposta (a avaliação só mede o SQL)."""
        context = self._recent_turns(history)
        messages: list[Message] = [{"role": "system", "content": self._sql_system_prompt}]
        for turn in context:
            # cada pergunta anterior vira um par user/assistant, com o SQL que funcionou
            messages += [
                {"role": "user", "content": turn.question},
                {"role": "assistant", "content": f"```sql\n{turn.sql}\n```"},
            ]
        messages.append({"role": "user", "content": question})
        attempts: list[Attempt] = []

        for _ in range(self.max_attempts):
            reply = self.llm.complete(messages)

            reason = no_sql_reason(reply)
            if reason is not None:
                return AgentResult(question, "unanswerable", reason, attempts=attempts)

            sql = ""
            try:
                sql = extract_sql(reply)
                validate_sql(sql, self.tables)
                result = self.db.run(sql, max_rows=self.max_rows, timeout_s=self.timeout_s)
            except UnsafeSQLError as exc:
                attempts.append(Attempt(sql, str(exc)))
                answer = f"Consulta bloqueada: {exc} Este agente só faz consultas de leitura."
                return AgentResult(question, "blocked", answer, sql=sql, attempts=attempts)
            except SQLError as exc:
                attempts.append(Attempt(sql, str(exc)))
                # mesma conversa: o modelo vê o que escreveu e o erro que deu
                error = str(exc)[:MAX_ERROR_CHARS]
                messages += [
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content": self._fix_prompt.replace("{error}", error)},
                ]
                continue

            attempts.append(Attempt(sql))
            answer = self._answer_or_fallback(question, sql, result, context) if explain else ""
            return AgentResult(
                question,
                "ok",
                answer,
                sql=sql,
                rows=result.rows,
                truncated=result.truncated,
                attempts=attempts,
            )

        answer = (
            f"Não consegui montar uma consulta válida em {self.max_attempts} tentativas. "
            "Tente reformular a pergunta."
        )
        return AgentResult(question, "failed", answer, sql=attempts[-1].sql, attempts=attempts)

    def answer(
        self,
        question: str,
        sql: str,
        result: QueryResult,
        context: Sequence[AgentResult] = (),
    ) -> str:
        content = self._describe_result(question, sql, result)
        if context:
            # "e por estado?" sozinho não diz do que se trata; a pergunta anterior diz
            content = f"Pergunta anterior da conversa: {context[-1].question}\n\n{content}"
        return self.llm.complete(
            [
                {"role": "system", "content": self._answer_system_prompt},
                {"role": "user", "content": content},
            ]
        )

    def _recent_turns(self, history: Sequence[AgentResult]) -> list[AgentResult]:
        # só turnos que deram certo: SQL com erro ou bloqueado não é exemplo a seguir
        usable = [r for r in history if r.ok and r.sql]
        return usable[-self.max_history :] if self.max_history else []

    def _answer_or_fallback(
        self, question: str, sql: str, result: QueryResult, context: Sequence[AgentResult]
    ) -> str:
        # a consulta já deu certo: se o LLM falhar agora, a tabela ainda vale ser mostrada
        try:
            return self.answer(question, sql, result, context)
        except LLMError:
            return "Consulta executada, mas não consegui gerar a explicação agora. Veja a tabela."

    def _describe_result(self, question: str, sql: str, result: QueryResult) -> str:
        rows = result.rows
        total = len(rows)
        shown = min(total, self.sample_rows)
        if result.truncated:
            header = f"Resultado: cortado no limite de {total} linhas (há mais linhas no banco)"
        else:
            header = f"Resultado: {total} linha(s)"
        if shown < total:
            header += f", mostrando as primeiras {shown}"
        sample = rows.head(shown).to_csv(index=False, lineterminator="\n") if total else "(vazio)"
        return f"Pergunta: {question}\n\nSQL:\n{sql}\n\n{header}\n{sample}"


def build_agent(settings: Settings | None = None) -> Agent:
    """Monta o agente a partir do `.env` (provedor, banco e limites)."""
    settings = settings or load_settings()
    return Agent(
        get_llm(settings),
        Database(settings.db_path),
        max_attempts=settings.agent_max_attempts,
        max_rows=settings.sql_max_rows,
        timeout_s=settings.sql_timeout_seconds,
    )
