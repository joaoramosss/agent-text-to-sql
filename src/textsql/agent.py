"""O agente: pergunta -> SQL -> execução -> resposta em português.

Duas chamadas ao LLM por pergunta, com responsabilidades separadas:
1. `generate_sql`: só escreve SQL (prompt com o schema).
2. `answer`: só redige a resposta (prompt com pergunta, SQL e amostra do resultado).

O agente não imprime nada; devolve um `AgentResult` que a interface formata.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from textsql.db import Database
from textsql.llm.base import LLMClient
from textsql.prompts import load_prompt
from textsql.schema import schema_description
from textsql.sql_utils import extract_sql


@dataclass
class AgentResult:
    question: str
    sql: str
    rows: pd.DataFrame
    answer: str


class Agent:
    def __init__(self, llm: LLMClient, db: Database, *, sample_rows: int = 20):
        self.llm = llm
        self.db = db
        self.sample_rows = sample_rows
        # o schema é estático: monta o system prompt uma vez só
        self._sql_system_prompt = load_prompt("generate_sql").replace(
            "{schema}", schema_description(db)
        )
        self._answer_system_prompt = load_prompt("answer")

    def ask(self, question: str) -> AgentResult:
        sql = self.generate_sql(question)
        rows = self.execute(sql)
        answer = self.answer(question, sql, rows)
        return AgentResult(question=question, sql=sql, rows=rows, answer=answer)

    def generate_sql(self, question: str) -> str:
        text = self.llm.complete(
            [
                {"role": "system", "content": self._sql_system_prompt},
                {"role": "user", "content": question},
            ]
        )
        return extract_sql(text)

    def execute(self, sql: str) -> pd.DataFrame:
        return self.db.query(sql)

    def answer(self, question: str, sql: str, rows: pd.DataFrame) -> str:
        return self.llm.complete(
            [
                {"role": "system", "content": self._answer_system_prompt},
                {"role": "user", "content": self._describe_result(question, sql, rows)},
            ]
        )

    def _describe_result(self, question: str, sql: str, rows: pd.DataFrame) -> str:
        total = len(rows)
        shown = min(total, self.sample_rows)
        header = f"Resultado: {total} linha(s)"
        if shown < total:
            header += f", mostrando as primeiras {shown}"
        sample = rows.head(shown).to_csv(index=False, lineterminator="\n") if total else "(vazio)"
        return f"Pergunta: {question}\n\nSQL:\n{sql}\n\n{header}\n{sample}"
