import pandas as pd
import pytest

from textsql.display import (
    MAX_BARS,
    ChartSpec,
    as_time,
    escape_markdown,
    format_number,
    suggest_chart,
)


def test_vazio_sem_grafico():
    assert suggest_chart(pd.DataFrame({"x": []})) is None


def test_uma_linha_vira_metricas():
    df = pd.DataFrame({"qtd_pedidos": [96478], "ticket_medio": [137.5], "nome": ["x"]})
    assert suggest_chart(df) == ChartSpec("metric", metrics=("qtd_pedidos", "ticket_medio"))


def test_uma_linha_so_texto_sem_grafico():
    assert suggest_chart(pd.DataFrame({"estado": ["SP"]})) is None


def test_data_e_numero_vira_linha():
    df = pd.DataFrame(
        {"mes": pd.to_datetime(["2018-01-01", "2018-02-01"]), "receita": [10.0, 20.0]}
    )
    assert suggest_chart(df) == ChartSpec("line", x="mes", y="receita")


def test_texto_ano_mes_vira_linha():
    df = pd.DataFrame({"periodo": ["2018-01", "2018-02", "2018-03"], "pedidos": [5, 7, 9]})
    assert suggest_chart(df) == ChartSpec("line", x="periodo", y="pedidos")


def test_ano_numerico_pelo_nome_vira_linha():
    df = pd.DataFrame({"ano": [2016, 2017, 2018], "pedidos": [300, 45000, 54000]})
    assert suggest_chart(df) == ChartSpec("line", x="ano", y="pedidos")


def test_categoria_e_numero_vira_barra_com_a_primeira_medida():
    df = pd.DataFrame({"estado": ["SP", "RJ"], "pedidos": [100, 50], "receita": [1.0, 2.0]})
    assert suggest_chart(df) == ChartSpec("bar", x="estado", y="pedidos")


def test_muitas_categorias_fica_so_a_tabela():
    df = pd.DataFrame({"cidade": [f"c{i}" for i in range(MAX_BARS + 1)], "n": range(MAX_BARS + 1)})
    assert suggest_chart(df) is None


def test_categoria_repetida_nao_vira_barra():
    df = pd.DataFrame({"estado": ["SP", "SP"], "tipo": ["a", "b"], "n": [1, 2]})
    assert suggest_chart(df) is None


def test_so_numeros_sem_tempo_sem_grafico():
    df = pd.DataFrame({"preco": [1.0, 2.0], "frete": [3.0, 4.0]})
    assert suggest_chart(df) is None


def test_as_time_converte_texto():
    converted = as_time(pd.Series(["2018-01", "2018-02"]))
    assert pd.api.types.is_datetime64_any_dtype(converted)
    assert converted.iloc[1] == pd.Timestamp("2018-02-01")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(96478, "96.478"), (1234.5, "1.234,50"), (12.0, "12"), (0.25, "0,25"), (float("nan"), "—")],
)
def test_formato_brasileiro(value, expected):
    assert format_number(value) == expected


def test_escapa_cifrao_para_nao_virar_latex():
    assert escape_markdown("de R$ 10 para R$ 20") == r"de R\$ 10 para R\$ 20"
