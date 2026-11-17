"""Fixtures compartilhadas: um Olist minúsculo gerado em disco, sem depender do download."""

from pathlib import Path

import pytest

from textsql.db import Database
from textsql.load import load_olist

# cabeçalhos iguais aos CSVs reais do Kaggle
MINI_OLIST: dict[str, list[str]] = {
    "olist_customers_dataset.csv": [
        "customer_id,customer_unique_id,customer_zip_code_prefix,customer_city,customer_state",
        "c1,u1,01003,sao paulo,SP",
        "c2,u1,20000,rio de janeiro,RJ",
    ],
    "olist_geolocation_dataset.csv": [
        "geolocation_zip_code_prefix,geolocation_lat,geolocation_lng,geolocation_city,geolocation_state",
        "01003,-23.5,-46.6,sao paulo,SP",
        "01003,-23.6,-46.7,sao paulo,SP",
        "20000,-22.9,-43.2,rio de janeiro,RJ",
    ],
    "olist_order_items_dataset.csv": [
        "order_id,order_item_id,product_id,seller_id,shipping_limit_date,price,freight_value",
        "o1,1,p1,s1,2018-01-05 10:00:00,100.0,10.0",
        "o1,2,p2,s1,2018-01-05 10:00:00,50.0,5.0",
        "o2,1,p1,s1,2018-02-05 10:00:00,100.0,10.0",
    ],
    "olist_order_payments_dataset.csv": [
        "order_id,payment_sequential,payment_type,payment_installments,payment_value",
        "o1,1,credit_card,3,165.0",
        "o2,1,boleto,1,110.0",
    ],
    "olist_order_reviews_dataset.csv": [
        "review_id,order_id,review_score,review_comment_title,review_comment_message,"
        "review_creation_date,review_answer_timestamp",
        "r1,o1,5,,otimo,2018-01-10 00:00:00,2018-01-11 00:00:00",
        "r2,o2,2,,,2018-02-10 00:00:00,2018-02-11 00:00:00",
    ],
    "olist_orders_dataset.csv": [
        "order_id,customer_id,order_status,order_purchase_timestamp,order_approved_at,"
        "order_delivered_carrier_date,order_delivered_customer_date,order_estimated_delivery_date",
        "o1,c1,delivered,2018-01-01 12:00:00,2018-01-01 12:30:00,2018-01-02 00:00:00,"
        "2018-01-08 00:00:00,2018-01-15 00:00:00",
        "o2,c2,canceled,2018-02-01 12:00:00,,,,2018-02-15 00:00:00",
    ],
    "olist_products_dataset.csv": [
        "product_id,product_category_name,product_name_lenght,product_description_lenght,"
        "product_photos_qty,product_weight_g,product_length_cm,product_height_cm,product_width_cm",
        "p1,beleza_saude,40,500,1,200,10,10,10",
        "p2,cama_mesa_banho,30,300,2,1000,30,10,30",
    ],
    "olist_sellers_dataset.csv": [
        "seller_id,seller_zip_code_prefix,seller_city,seller_state",
        "s1,01003,sao paulo,SP",
    ],
    "product_category_name_translation.csv": [
        "product_category_name,product_category_name_english",
        "beleza_saude,health_beauty",
        "cama_mesa_banho,bed_bath_table",
    ],
}


@pytest.fixture(scope="session")
def mini_source(tmp_path_factory) -> Path:
    source = tmp_path_factory.mktemp("olist_raw")
    for name, lines in MINI_OLIST.items():
        (source / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return source


@pytest.fixture(scope="session")
def mini_db_path(mini_source, tmp_path_factory) -> Path:
    db_path = tmp_path_factory.mktemp("olist_db") / "mini.duckdb"
    load_olist(mini_source, db_path)
    return db_path


@pytest.fixture
def mini_db(mini_db_path):
    with Database(mini_db_path) as db:
        yield db
