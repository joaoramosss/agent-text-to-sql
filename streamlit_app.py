"""Interface web do agente.

Rode: uv run streamlit run streamlit_app.py

O app só desenha: perguntar é com o `Agent`, escolher o gráfico é com `display.py`.
O histórico da conversa fica em `st.session_state` (um por aba do navegador) e é passado
ao agente a cada pergunta; o agente em si é um só, compartilhado e sem estado.
"""

from __future__ import annotations

import logging

import altair as alt
import pandas as pd
import streamlit as st

from textsql.agent import AgentResult, build_agent
from textsql.display import (
    ChartSpec,
    as_time,
    escape_markdown,
    format_number,
    spans_frame,
    suggest_chart,
)
from textsql.errors import LLMError

# uma linha por pergunta no console / logs da hospedagem (ver tracing.LoggingTraceSink)
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("textsql").setLevel(logging.INFO)

# azul validado para daltonismo e contraste (claro / escuro)
BAR_COLOR = {"light": "#2a78d6", "dark": "#3987e5"}

EXAMPLES = [
    "Quais as 10 categorias com maior receita?",
    "Como evoluiu o faturamento mês a mês em 2017?",
    "Qual o tempo médio de entrega por estado?",
    "Qual a nota média das avaliações por tipo de pagamento?",
]


@st.cache_resource(show_spinner="Abrindo o banco...")
def get_agent():
    return build_agent()


def main() -> None:
    st.set_page_config(page_title="Analista de dados Olist", page_icon="📊")
    st.title("Analista de dados Olist")
    st.caption(
        "Pergunte em português sobre ~100 mil pedidos de e-commerce (2016–2018). "
        "O agente escreve o SQL, executa e explica o resultado."
    )

    try:
        agent = get_agent()
    except (ValueError, FileNotFoundError) as exc:  # chave do LLM ausente, banco não gerado
        st.error(f"Configuração incompleta: {exc}")
        st.stop()

    history: list[AgentResult] = st.session_state.setdefault("history", [])
    sidebar(history)

    for i, result in enumerate(history):
        with st.chat_message("user"):
            st.markdown(escape_markdown(result.question))
        with st.chat_message("assistant"):
            render_result(result, key=str(i))

    question = st.chat_input("Ex.: qual estado tem mais clientes?")
    question = question or st.session_state.pop("pending_question", None)
    if not question:
        return

    with st.chat_message("user"):
        st.markdown(escape_markdown(question))
    with st.chat_message("assistant"):
        try:
            with st.spinner("Gerando e executando o SQL..."):
                result = agent.ask(question, history)
        except LLMError as exc:
            st.error(
                f"O provedor de LLM falhou (rede ou limite de requisições). Tente de novo.\n\n{exc}"
            )
            return
        render_result(result, key=str(len(history)))
    history.append(result)


def sidebar(history: list[AgentResult]) -> None:
    with st.sidebar:
        st.subheader("Exemplos")
        for example in EXAMPLES:
            st.button(
                example,
                width="stretch",
                on_click=st.session_state.update,
                kwargs={"pending_question": example},
            )
        st.divider()
        if st.button("Nova conversa", disabled=not history):
            history.clear()
            st.rerun()
        st.caption(
            "Só leitura: o SQL passa por validação e roda num banco sem permissão de escrita, "
            "com limite de linhas e de tempo."
        )


def render_result(result: AgentResult, key: str) -> None:
    if result.status == "ok":
        st.markdown(escape_markdown(result.answer))
        render_data(result, key)
    elif result.status == "unanswerable":
        st.info(result.answer)
    elif result.status == "blocked":
        st.warning(result.answer)
    else:
        st.error(result.answer)

    if result.attempts or result.trace:
        render_details(result, key)


def render_data(result: AgentResult, key: str) -> None:
    df = result.rows
    if df is None:
        return
    spec = suggest_chart(df)
    if spec and spec.kind == "metric":
        for col, name in zip(st.columns(len(spec.metrics)), spec.metrics, strict=True):
            col.metric(name, format_number(df[name].iloc[0]))
    elif spec:
        st.altair_chart(build_chart(df, spec), width="stretch", key=f"chart-{key}")

    note = " — limite atingido, há mais linhas no banco" if result.truncated else ""
    with st.expander(f"Tabela ({len(df)} linha(s){note})", expanded=spec is None):
        st.dataframe(df, hide_index=True, key=f"table-{key}")


# Vega-Lite formata números no padrão americano (1,234.5); troca vírgula por ponto nos eixos
BR_AXIS = alt.Axis(labelExpr="replace(format(datum.value, ',~r'), /,/g, '.')")


def build_chart(df: pd.DataFrame, spec: ChartSpec) -> alt.Chart:
    color = BAR_COLOR.get(_theme(), BAR_COLOR["light"])
    # o tooltip mostra o valor já formatado em Python (1.234,56), não o formato do Vega
    data = df[[spec.x, spec.y]].assign(valor=df[spec.y].map(format_number))
    tooltip = [alt.Tooltip(spec.x, title=spec.x), alt.Tooltip("valor:N", title=spec.y)]

    if spec.kind == "line":
        data[spec.x] = as_time(data[spec.x])
        is_date = pd.api.types.is_datetime64_any_dtype(data[spec.x])
        x = (
            alt.X(f"{spec.x}:T", title=None, axis=alt.Axis(format="%m/%Y"))
            if is_date
            else alt.X(f"{spec.x}:O", title=None)
        )
        if is_date:
            tooltip[0] = alt.Tooltip(f"{spec.x}:T", title=spec.x, format="%d/%m/%Y")
        return (
            alt.Chart(data)
            .mark_line(color=color, strokeWidth=2, point=alt.OverlayMarkDef(size=64, color=color))
            .encode(x=x, y=alt.Y(f"{spec.y}:Q", title=spec.y, axis=BR_AXIS), tooltip=tooltip)
        )

    # barras horizontais: nomes longos (categorias, cidades) cabem; ordem = a do SQL
    return (
        alt.Chart(data)
        .mark_bar(color=color, cornerRadiusEnd=4, height={"band": 0.8})
        .encode(
            y=alt.Y(f"{spec.x}:N", sort=None, title=None),
            x=alt.X(f"{spec.y}:Q", title=spec.y, axis=BR_AXIS),
            tooltip=tooltip,
        )
        .properties(height=max(120, 26 * len(df)))
    )


def render_details(result: AgentResult, key: str) -> None:
    failed = [a for a in result.attempts if a.error]
    label = "SQL e etapas" if not failed else f"SQL e etapas ({len(result.attempts)} tentativas)"
    with st.expander(label):
        for i, attempt in enumerate(result.attempts, 1):
            if len(result.attempts) > 1:
                st.markdown(f"**Tentativa {i}**")
            if attempt.sql:
                st.code(attempt.sql, language="sql")
            if attempt.error:
                st.caption(f"Erro: {attempt.error}")

        trace = result.trace
        if trace:
            st.markdown("**Etapas**")
            st.dataframe(spans_frame(trace), hide_index=True, key=f"trace-{key}")
            st.caption(
                f"{format_number(trace.duration_ms / 1000)} s · {trace.llm_calls} chamada(s) ao "
                f"LLM · {format_number(trace.tokens)} tokens · trace `{trace.trace_id}` · "
                f"prompt `{trace.prompt_version}`"
            )


def _theme() -> str:
    try:
        return st.context.theme.type or "light"
    except AttributeError:  # versões antigas do Streamlit
        return "light"


main()
