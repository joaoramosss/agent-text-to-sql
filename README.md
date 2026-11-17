# agent-text-to-sql

Agente conversacional que responde perguntas em português sobre dados de e-commerce (dataset Olist):
pergunta → lê o schema → gera SQL → executa no DuckDB → corrige sozinho se der erro → responde com tabela/gráfico e explicação curta.

> Em construção. Etapa atual: **4 — Robustez** (guardrails, limites e autocorreção).

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
  db.py             conexão blindada (read-only, sem acesso externo), limite de linhas e timeout
  guardrails.py     valida o SQL do LLM pela AST (sqlglot) antes de executar
  errors.py         exceções: corrigível (volta ao LLM) x bloqueio x falha do provedor
  schema.py         descrição do schema para o prompt (DDL gerado + notas de negócio)
  agent.py          pergunta -> SQL -> validação -> execução -> resposta, com autocorreção
  sql_utils.py      extrai o SQL da resposta do modelo
  prompts/          textos que vão para o LLM (.md), carregados por load_prompt()
scripts/            utilitários de linha de comando
tests/              pytest (usa um Olist em miniatura; testes do banco real pulam se ele não existir)
data/               dataset e banco (não versionados)
```

## Arquitetura e trade-offs

### Fluxo do agente

```
pergunta ─► LLM gera SQL ─► guardrails ─► DuckDB (limite + timeout) ─► LLM redige resposta
               ▲                │  │                │
               └── erro corrigível (sintaxe, coluna inexistente, timeout): até 3 tentativas
                                   └─► bloqueio de segurança: para na hora, sem nova tentativa
```

`Agent.ask()` devolve um `AgentResult` com `status`:
`ok` | `unanswerable` (o modelo respondeu `SEM_SQL:`) | `blocked` | `failed` (esgotou tentativas),
além do histórico de tentativas (`attempts`).

### Segurança em camadas

| Camada | O que faz | Por que não basta sozinha |
|---|---|---|
| Prompt | pede só `SELECT`; dá a saída `SEM_SQL:` para pedidos fora do escopo | o modelo pode desobedecer ou ser induzido |
| `guardrails.py` (AST) | um único comando de leitura; nenhum DML/DDL na árvore (nem em CTE); só tabelas do schema; sem funções de arquivo/rede/ambiente | outro parser pode divergir do DuckDB; denylist de funções é incompleta |
| `db.py` (motor) | `read_only`, `enable_external_access=false`, `lock_configuration=true`; parser do DuckDB confirma um único `SELECT` | `read_only` ainda permite `CREATE TEMP TABLE`, por isso a AST |

Limites: `SQL_MAX_ROWS` (padrão 1000, detectado com `LIMIT N+1`), `SQL_TIMEOUT_SECONDS`
(padrão 10, via `interrupt()`), `AGENT_MAX_ATTEMPTS` (padrão 3).
