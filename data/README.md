# Dados

Dataset: **Brazilian E-Commerce Public Dataset by Olist** (Kaggle)
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

```bash
uv run python scripts/load_data.py                   # baixa via kagglehub (sem conta Kaggle) e carrega
uv run python scripts/load_data.py --source data/raw # ou use CSVs já baixados manualmente
```

- `raw/` — lugar para CSVs baixados à mão (ignorados no git).
- `olist.duckdb` — banco gerado (ignorado no git). ~100 mil pedidos, set/2016 a out/2018.

Tabelas: `orders`, `order_items`, `order_payments`, `order_reviews`, `customers`, `sellers`,
`products`, `category_translation`, `geolocation` (agregada: 1 linha por prefixo de CEP).

O que o agente sabe sobre o schema está em `src/textsql/prompts/schema_notes.md`.
