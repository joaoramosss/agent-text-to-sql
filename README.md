# agent-text-to-sql

Agente conversacional que responde perguntas em português sobre dados de e-commerce (dataset Olist):
pergunta → lê o schema → gera SQL → executa no DuckDB → corrige sozinho se der erro → responde com tabela/gráfico e explicação curta.

> Em construção. Etapa atual: **3 — MVP no terminal**.

```
$ uv run python scripts/chat.py "Qual o tempo médio de entrega em dias?"

SQL:
SELECT round(avg(datediff('day', order_purchase_timestamp, order_delivered_customer_date)), 2)
  AS tempo_medio_entrega_dias
FROM orders
WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL

Resultado (1 linha(s)):
 tempo_medio_entrega_dias
                     12.5

Resposta: O tempo médio de entrega foi de 12,5 dias.
```

## Stack

- Python 3.12, gerenciado com [uv](https://docs.astral.sh/uv/)
- DuckDB (banco analítico embutido)
- LLM via API compatível com OpenAI — Groq (free tier) por padrão, OpenRouter como alternativa
- Agente em Python puro (sem framework de agentes)

## Como rodar

```bash
uv sync                               # cria .venv e instala tudo a partir do uv.lock
cp .env.example .env                  # preencha GROQ_API_KEY
uv run python scripts/check_llm.py    # testa a conexão com o LLM
uv run python scripts/load_data.py    # baixa o Olist (sem conta Kaggle) e gera data/olist.duckdb
uv run python scripts/chat.py         # pergunte no terminal (ou passe a pergunta como argumento)
uv run pytest                         # testes
uv run ruff check .                   # lint
```

## Estrutura

```
src/textsql/        código do agente
  config.py         leitura e validação do .env
  llm/              interface de LLM (trocar de provedor = mudar LLM_PROVIDER no .env)
  load.py           carga dos CSVs do Olist no DuckDB
  db.py             conexão somente leitura e consultas
  schema.py         descrição do schema para o prompt (DDL gerado + notas de negócio)
  agent.py          pergunta -> SQL -> execução -> resposta (duas chamadas ao LLM)
  sql_utils.py      extrai o SQL da resposta do modelo
  prompts/          textos que vão para o LLM (.md), carregados por load_prompt()
scripts/            utilitários de linha de comando
tests/              pytest (usa um Olist em miniatura; testes do banco real pulam se ele não existir)
data/               dataset e banco (não versionados)
```

## Arquitetura e trade-offs

_Seção preenchida ao longo das etapas._
