# agent-text-to-sql

Agente conversacional que responde perguntas em português sobre dados de e-commerce (dataset
público Olist): lê o schema, gera SQL, valida, executa no DuckDB, corrige sozinho se der erro e
responde com tabela, gráfico e uma explicação curta.

## Como funciona

```
pergunta (+ histórico da conversa)
  └─► LLM gera SQL ── prompt: regras + schema (DDL gerado + notas de negócio)
        ├─ "SEM_SQL: motivo" ─► status unanswerable (pergunta fora dos dados)
        └─► guardrails.validate_sql (AST com sqlglot)
              ├─ UnsafeSQLError ─► status blocked (nunca volta ao LLM)
              └─► Database.run (read-only, sem acesso externo, LIMIT N+1, timeout)
                    ├─ SQLError ─► erro volta ao LLM na mesma conversa (até AGENT_MAX_ATTEMPTS)
                    └─► LLM redige a resposta ─► status ok
```

- `Agent.ask(pergunta, history)` devolve um `AgentResult` (status, SQL, linhas, resposta,
  tentativas). O agente não guarda estado; quem chama passa o histórico.
- Exceções: `SQLError` (corrigível, volta ao LLM), `UnsafeSQLError` (bloqueio), `LLMError`
  (falha do provedor). Ver `src/textsql/errors.py`.
- Segurança em 3 camadas: prompt → validação da AST (só um SELECT, só tabelas do schema, sem
  funções de arquivo/rede) → DuckDB travado (`read_only`, `enable_external_access=false`,
  `lock_configuration=true`, parser do DuckDB confirma um único SELECT).

## Estrutura

```
src/textsql/
  config.py        Settings lidas do .env (único lugar que conhece os nomes das variáveis)
  llm/             contrato LLMClient (Protocol) + cliente OpenAI-compatível + get_llm()
  load.py          carga dos CSVs do Olist no DuckDB
  db.py            conexão blindada; run() com limite de linhas e timeout
  guardrails.py    validação do SQL do LLM
  errors.py        exceções do projeto
  schema.py        descrição do schema para o prompt
  agent.py         o agente; build_agent() monta tudo a partir do .env
  sql_utils.py     extrai SQL / SEM_SQL da resposta do modelo
  display.py       escolha do gráfico e formatação pt-BR (sem Streamlit, testável)
  evaluation.py    comparação de resultados para a avaliação
  prompts/*.md     todo texto enviado ao LLM
streamlit_app.py   interface web
scripts/           check_llm, load_data, chat (terminal), evaluate
eval/              questions.toml (perguntas + SQL de referência) e results/ (cada rodada)
tests/             pytest; Olist em miniatura no conftest, FakeLLM, sem rede
data/              CSVs e banco gerado (não versionados)
```

## Comandos

```bash
uv sync                                 # ambiente a partir do uv.lock
cp .env.example .env                    # preencha a chave do provedor
uv run python scripts/load_data.py      # baixa o Olist e gera data/olist.duckdb
uv run streamlit run streamlit_app.py   # interface web
uv run python scripts/chat.py           # terminal
uv run python scripts/evaluate.py       # taxa de acerto (usa o LLM real; ~6 min no free tier)
uv run pytest                           # testes (rápidos, sem rede)
uv run ruff check . && uv run ruff format .
```

## Configuração (.env)

`LLM_PROVIDER` (groq | openrouter), `LLM_MODEL`, `GROQ_API_KEY` / `OPENROUTER_API_KEY`,
`DB_PATH`, `SQL_MAX_ROWS` (1000), `SQL_TIMEOUT_SECONDS` (10), `AGENT_MAX_ATTEMPTS` (3).
Toda variável nova entra em `config.ENV_VARS` e no `.env.example` (há teste que confere).

## Convenções

- Segredos só no `.env` (nunca versionado). Nunca ler, imprimir ou commitar o `.env`.
- Testes não chamam rede: use `FakeLLM` e o banco em miniatura de `tests/conftest.py`.
  Toda mudança de comportamento vem com teste.
- Texto para o LLM fica em `src/textsql/prompts/*.md`, não em strings no código.
- Guardrails: não afrouxar nenhuma camada sem um teste novo em `tests/test_guardrails.py`
  mostrando que o caso é seguro.
- Mudou prompt, notas do schema ou modelo? Rode `scripts/evaluate.py` e compare com a última
  rodada em `eval/results/`. Não ajuste o prompt só para passar numa pergunta específica.
- Lógica fica em `src/` (importável, testável); `scripts/` e `streamlit_app.py` só orquestram.
- Python 3.12, `uv`, ruff (linha de 100). Commits em Conventional Commits (feat, fix, docs, chore).

## Fluxo de trabalho

Uma etapa do roadmap por vez: propor o plano, implementar, testes e ruff passando, README
atualizado, um commit por etapa.

## Roadmap

1. ✅ Setup: ambiente, estrutura, provedor de LLM atrás de interface
2. ✅ Dados: Olist no DuckDB, carga reproduzível, descrição do schema
3. ✅ MVP no terminal: pergunta → SQL → resultado → resposta
4. ✅ Robustez: guardrails, limite de linhas, timeout, autocorreção
5. ✅ Interface Streamlit com gráficos e memória de conversa
6. ✅ Avaliação: 30 perguntas, comparação por resultado (29/30)
7. Observabilidade: tracing de cada etapa do agente (prompt, SQL, tentativas, tempo)
8. Deploy da demo, README final e GIF
