"""Streamlit dashboard for the Wallex AI Assistant.

This is the read-only portfolio UI. It fetches public market data, optionally
reads account balances when a Wallex API key is configured, and presents the
results in a small, modular dashboard without allowing any trading actions.
"""

from __future__ import annotations

from decimal import Decimal

import streamlit as st

from wallex_assistant.config import get_settings
from wallex_assistant.i18n import format_money, format_quantity, t
from wallex_assistant.portfolio import (
    generate_analysis,
    get_asset_values,
    get_market_stats,
    get_portfolio_balances,
    value_portfolio,
)


def _build_table_rows(balances: list, market_stats: list) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in get_asset_values(balances, market_stats):
        rows.append(
            {
                "asset": item["asset"],
                "quantity": str(item["quantity"]),
                "price": str(item["price"]),
                "value_tmn": str(item["value_tmn"]),
            }
        )
    return rows


def main() -> None:
    """Render the portfolio dashboard."""
    settings = get_settings()
    language = settings.language if settings.language in {"en", "fa"} else "en"

    st.set_page_config(page_title="Wallex AI Assistant", page_icon="📊", layout="wide")
    st.title(t("app.title", language))
    st.caption(t("app.subtitle", language))
    st.info(t("app.readonly_notice", language))

    with st.sidebar:
        st.selectbox(
            t("app.language", language),
            ["en", "fa"],
            index=0 if language == "en" else 1,
            key="lang_select",
        )
        if st.button("Refresh", type="primary"):
            st.rerun()

    language = st.session_state.get("lang_select", language)

    try:
        market_stats = get_market_stats(settings)
    except Exception as exc:  # pragma: no cover - UI path
        st.error(f"Unable to load market data: {exc}")
        market_stats = []

    if settings.has_wallex_key:
        try:
            balances = get_portfolio_balances(settings)
        except Exception as exc:  # pragma: no cover - UI path
            st.error(f"Unable to load account balances: {exc}")
            balances = []
    else:
        balances = []
        st.warning("No WALLEX_API_KEY was configured. Showing public market data only.")

    total_value = value_portfolio(balances, market_stats)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total portfolio value", format_money(total_value, language))
    with col2:
        st.metric("Assets tracked", str(len(balances)))
    with col3:
        st.metric("Market symbols", str(len(market_stats)))

    tab_overview, tab_balances, tab_analysis = st.tabs(
        [t("tab.overview", language), t("tab.balances", language), t("tab.analysis", language)]
    )

    with tab_overview:
        if not market_stats:
            st.info("No public market data was available.")
        else:
            symbol_price = {
                stat.symbol: float(stat.last_price) if stat.last_price is not None else 0.0
                for stat in market_stats
            }
            st.bar_chart(symbol_price)

    with tab_balances:
        if not balances:
            st.info(t("portfolio.empty", language))
        else:
            rows = _build_table_rows(balances, market_stats)
            st.dataframe(rows, use_container_width=True)

    with tab_analysis:
        if st.button(t("analysis.run", language), type="primary"):
            with st.spinner(t("analysis.running", language)):
                analysis = generate_analysis(
                    balances=balances,
                    market_stats=market_stats,
                    language=language,
                )
            st.session_state["analysis_result"] = analysis

        analysis_result = st.session_state.get("analysis_result")
        if analysis_result:
            st.write(analysis_result)
        else:
            st.write(t("analysis.empty", language))


if __name__ == "__main__":
    main()
