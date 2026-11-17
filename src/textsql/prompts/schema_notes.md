## Sobre os dados

Dataset público da Olist: ~100 mil pedidos de e-commerce no Brasil, de setembro/2016 a
outubro/2018. Nomes de colunas em inglês; cidades, estados e categorias em português.
Dialeto SQL: **DuckDB**.

## Tabelas

- **orders** — 1 linha por pedido. `order_status` tem os valores: `delivered`, `shipped`,
  `canceled`, `unavailable`, `invoiced`, `processing`, `created`, `approved`.
  Para "vendas" ou "pedidos concluídos", filtre `order_status = 'delivered'`.
  Datas: `order_purchase_timestamp` (compra), `order_approved_at`, `order_delivered_carrier_date`
  (postado), `order_delivered_customer_date` (entregue; NULL se não entregue),
  `order_estimated_delivery_date` (previsão). Atraso = entregue depois da previsão.
- **order_items** — 1 linha por item do pedido. `order_item_id` é a sequência (1, 2, 3...) dentro
  do pedido, não um id global. `price` é o preço do item e `freight_value` o frete do item.
  Valor total do pedido = `sum(price + freight_value)` agrupado por `order_id`.
- **order_payments** — 1 ou mais linhas por pedido (`payment_sequential`). `payment_type`:
  `credit_card`, `boleto`, `voucher`, `debit_card`, `not_defined`. `payment_value` já inclui frete.
  `payment_installments` = número de parcelas.
- **order_reviews** — avaliação do pedido, `review_score` de 1 a 5. Comentários em
  `review_comment_message` (muitos NULL). `review_id` tem duplicatas; use `order_id` para joins.
- **customers** — 1 linha por pedido, não por pessoa: `customer_id` muda a cada pedido.
  Para contar clientes únicos ou recompra, use `customer_unique_id`.
  `customer_state` é a sigla (SP, RJ...). `customer_city` em minúsculas, sem acento.
- **sellers** — 1 linha por vendedor. `seller_state`, `seller_city` seguem o mesmo padrão.
- **products** — 1 linha por produto. `product_category_name` em português
  (ex.: `beleza_saude`, `cama_mesa_banho`). Dimensões em cm e peso em g.
- **category_translation** — mapeia `product_category_name` → `product_category_name_english`.
  Nem toda categoria tem tradução (LEFT JOIN).
- **geolocation** — 1 linha por prefixo de CEP (já agregada): média de latitude/longitude,
  cidade e estado mais frequentes.

## Joins

```
orders.customer_id        = customers.customer_id
orders.order_id           = order_items.order_id
orders.order_id           = order_payments.order_id
orders.order_id           = order_reviews.order_id
order_items.product_id    = products.product_id
order_items.seller_id     = sellers.seller_id
products.product_category_name     = category_translation.product_category_name
customers.customer_zip_code_prefix = geolocation.geolocation_zip_code_prefix
sellers.seller_zip_code_prefix     = geolocation.geolocation_zip_code_prefix
```

## Pegadinhas

- Um pedido pode ter vários itens, vários pagamentos e (raramente) várias reviews.
  Ao somar valores, agregue primeiro por `order_id` para não multiplicar linhas.
- Receita: use `order_items.price` (e `freight_value` se a pergunta incluir frete).
  `order_payments.payment_value` é o que o cliente pagou, com frete e possíveis vouchers.
- "Faturamento", "receita", "vendas" sem qualificação: considere pedidos `delivered`.
  Esse filtro vale só para essas métricas: pagamentos, avaliações, cadastros (clientes,
  vendedores, produtos) e contagens de pedidos não filtram status, salvo se a pergunta pedir.
- Datas são `TIMESTAMP`; para agrupar por mês use `date_trunc('month', coluna)`.
- Para agrupar ou filtrar por período ("por mês", "em 2017", "por ano"), use a data da compra,
  `order_purchase_timestamp`, a menos que a pergunta fale em entrega ou aprovação.
- Textos de cidade estão em minúsculas: compare com `lower()` ou escreva em minúsculas.
- Prefixos de CEP são texto com zero à esquerda (`'01003'`), não número.
