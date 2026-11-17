# agent-text-to-sql

Agente conversacional que responde perguntas em português sobre dados de e-commerce (dataset Olist):
pergunta → lê o schema → gera SQL → executa no DuckDB → corrige sozinho se der erro → responde com tabela/gráfico e explicação curta.

> Em construção. Etapa atual: **7 — Observabilidade** (trace de cada etapa do agente).

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
uv run streamlit run streamlit_app.py # interface web em http://localhost:8501
uv run python scripts/chat.py         # pergunte no terminal (ou passe a pergunta como argumento)
uv run python scripts/evaluate.py     # mede a taxa de acerto (eval/questions.toml -> eval/results/)
uv run python scripts/traces.py       # latência por etapa, retries, tokens e erros (logs/traces.jsonl)
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
  display.py        escolhe o gráfico pelo formato do resultado; formatação pt-BR
  evaluation.py     compara o resultado do agente com o de um SQL de referência
  tracing.py        trace/span de cada pergunta; destinos: JSONL e log
  prompts/          textos que vão para o LLM (.md), carregados por load_prompt()
streamlit_app.py    interface web: chat, gráfico, tabela e SQL de cada resposta
eval/               perguntas de avaliação com SQL de referência e resultados de cada rodada
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

### Avaliação

30 perguntas em `eval/questions.toml` (contagem, agregação, ranking, temporal, pegadinhas do
schema e 3 pedidos que devem ser recusados), cada uma com SQL de referência conferido à mão.
O script compara o **resultado** do SQL do agente com o da referência, não o texto do SQL
(*execution accuracy*): nomes de coluna ignorados, colunas extras aceitas, ordem só quando a
pergunta pede, tolerância numérica de 0,1%.

| Rodada | Mudança | Acerto |
|---|---|---|
| 1 | — | 26/30 (87%) |
| 2 | notas do schema: data da compra para períodos; filtro `delivered` só em vendas/receita; referência alternativa onde "vendido" é ambíguo | 28/30 (93%) |
| 3 | referência alternativa para "entregues em cada ano" (ano da compra ou da entrega) | **29/30 (97%)** |

Modelo `openai/gpt-oss-120b` (Groq), todas acertadas de primeira, latência média ~1 s por SQL.
Erro restante: em "valor total pago por tipo de pagamento" o agente filtra pedidos entregues
sem a pergunta pedir. Relatórios completos em `eval/results/`.

Limitações: 30 perguntas é pouco para separar modelos parecidos; o mesmo conjunto guiou os
ajustes do prompt (o ideal é um conjunto separado só para teste); o loop de autocorreção não foi
acionado nessas rodadas, então ele é coberto pelos testes unitários, não por esta métrica.

### Observabilidade

Cada pergunta gera um **trace** com um **span** por etapa (`generate_sql`, `validate`,
`execute`, `answer`; as três primeiras repetem a cada tentativa). Cada span guarda duração,
tentativa, entrada, saída, tokens e erro. O system prompt (~5 mil caracteres) não é repetido
em cada trace: vai um hash (`prompt_version`), que diz qual versão do prompt gerou cada resposta.

- `logs/traces.jsonl`: um trace por linha (fora do git; `TRACE_FILE=off` desliga).
- Log `textsql` (INFO): uma linha por pergunta, visível no console e nos logs da hospedagem.
- Interface: expander "SQL e etapas" com a linha do tempo; terminal: resumo de tempo e tokens.
- `scripts/traces.py`: p50/p95 por etapa, taxa de nova tentativa, tokens e erros mais comuns.

Falha ao gravar trace nunca derruba o agente; falha do LLM no meio também gera trace
(`status=llm_error`). Mesmo modelo de trace/span do OpenTelemetry, sem dependência externa.

Medição real (gpt-oss-120b na Groq): gerar SQL ~1,4 s (p50), validar ~12 ms, executar ~50 ms,
redigir a resposta ~1,1 s; ~2,6 mil tokens por pergunta. Com o limite de 8 mil tokens/minuto do
free tier, a demo comporta ~3 perguntas por minuto.

### Memória de conversa

O agente não guarda estado: quem chama passa o histórico (`agent.ask(pergunta, history)`).
As últimas 3 perguntas respondidas com sucesso entram no prompt como pares
pergunta → SQL, o que permite seguimentos como "e em 2018?". Sem estado, um único agente em cache
atende todas as sessões do Streamlit; o histórico de cada uma fica no `st.session_state`.

### Interface

| Resultado | Exibição |
|---|---|
| 1 linha | números em destaque (`st.metric`), formato brasileiro |
| tempo + número | linha (um único eixo Y; a 1ª medida) |
| categoria + número (até 30 linhas) | barras horizontais na ordem do SQL |
| outros | só a tabela |

A tabela e o SQL (com as tentativas que falharam) ficam sempre disponíveis em cada resposta.

### Segurança em camadas

| Camada | O que faz | Por que não basta sozinha |
|---|---|---|
| Prompt | pede só `SELECT`; dá a saída `SEM_SQL:` para pedidos fora do escopo | o modelo pode desobedecer ou ser induzido |
| `guardrails.py` (AST) | um único comando de leitura; nenhum DML/DDL na árvore (nem em CTE); só tabelas do schema; sem funções de arquivo/rede/ambiente | outro parser pode divergir do DuckDB; denylist de funções é incompleta |
| `db.py` (motor) | `read_only`, `enable_external_access=false`, `lock_configuration=true`; parser do DuckDB confirma um único `SELECT` | `read_only` ainda permite `CREATE TEMP TABLE`, por isso a AST |

Limites: `SQL_MAX_ROWS` (padrão 1000, detectado com `LIMIT N+1`), `SQL_TIMEOUT_SECONDS`
(padrão 10, via `interrupt()`), `AGENT_MAX_ATTEMPTS` (padrão 3).
