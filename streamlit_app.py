from __future__ import annotations

from decimal import Decimal

import streamlit as st

from wallex_assistant.config import Settings, get_settings
from wallex_assistant.errors import (
    WallexAPIError,
    WallexAuthError,
    WallexNetworkError,
    WallexNotFoundError,
    WallexRateLimitError,
    WallexResponseError,
)
from wallex_assistant.http import WallexHttpClient
from wallex_assistant.i18n import format_money, t
from wallex_assistant.portfolio import (
    generate_analysis,
    get_asset_values,
    get_market_stats,
    get_portfolio_balances,
    value_portfolio,
    get_buy_opportunities_with_context,
)


def build_runtime_settings(
    base_settings: Settings,
    api_key: str | None = None,
) -> Settings:
    """Return a settings snapshot using the key entered in the current UI session."""
    cleaned = (api_key or "").strip()
    if not cleaned:
        return base_settings
    return Settings(
        wallex_api_key=cleaned,
        wallex_base_url=base_settings.wallex_base_url,
        log_level=base_settings.log_level,
        language=base_settings.language,
        request_timeout=base_settings.request_timeout,
        max_retries=base_settings.max_retries,
        llm_provider=base_settings.llm_provider,
        llm_api_key=base_settings.llm_api_key,
    )


def validate_wallex_api_key(
    api_key: str,
    *,
    base_url: str,
    timeout: int,
    max_retries: int,
) -> tuple[bool, str]:
    """Validate the key with a read-only request without displaying API error details."""
    cleaned = (api_key or "").strip()
    if not cleaned:
        return False, "Enter a Wallex API key before connecting."

    client = WallexHttpClient(
        base_url=base_url,
        api_key=cleaned,
        timeout=timeout,
        max_retries=max_retries,
    )
    try:
        client.get("/v1/account/balances")
        return True, "Connected successfully. Your Wallex account is ready to load."
    except WallexAuthError:
        return False, "Wallex rejected the key. Check that it is valid and permitted for read-only account access."
    except WallexRateLimitError:
        return False, "Wallex rate-limited the request. Wait a moment and try again."
    except WallexNetworkError:
        return False, "The app could not reach Wallex. Check your network connection and try again."
    except WallexNotFoundError:
        return False, "The Wallex account endpoint was not found. Check the configured base URL."
    except WallexResponseError:
        return False, "Wallex returned an unexpected response. Please try again later."
    except WallexAPIError:
        return False, "Wallex returned an API error. Check your key and try again."
    except Exception:
        return False, "An unexpected validation error occurred. Please try again later."
    finally:
        client.close()


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
    """Render the read-only portfolio dashboard."""
    base_settings = get_settings()
    language = base_settings.language if base_settings.language in {"en", "fa"} else "en"

    st.set_page_config(page_title="Wallex AI Assistant", page_icon="📊", layout="wide")
    st.title(t("app.title", language))
    st.caption(t("app.subtitle", language))
    st.info(t("app.readonly_notice", language))

    st.session_state.setdefault("wallex_api_key", "")
    st.session_state.setdefault("wallex_status", "Not connected")
    st.session_state.setdefault("wallex_status_message", "No key entered in this session.")

    with st.sidebar:
        st.subheader("API Configuration")
        st.caption(
            "The key is held in Streamlit session state and is not written to a project file. "
            "Use this app only in a trusted environment."
        )
        show_key = st.checkbox("Show API key", value=False, key="show_wallex_api_key")
        st.text_input(
            "Wallex API key",
            type="default" if show_key else "password",
            key="wallex_api_key_input",
        )
        save_col, clear_col = st.columns(2)
        if save_col.button("Save & Connect", type="primary"):
            entered = st.session_state.get("wallex_api_key_input", "").strip()
            if not entered:
                st.session_state["wallex_api_key"] = ""
                st.session_state["wallex_status"] = "Not connected"
                st.session_state["wallex_status_message"] = "Enter a Wallex API key before connecting."
                st.warning(st.session_state["wallex_status_message"])
            else:
                st.session_state["wallex_api_key"] = entered
                connected, message = validate_wallex_api_key(
                    entered,
                    base_url=base_settings.wallex_base_url,
                    timeout=base_settings.request_timeout,
                    max_retries=base_settings.max_retries,
                )
                st.session_state["wallex_status"] = "Connected" if connected else "Connection failed"
                st.session_state["wallex_status_message"] = message
                (st.success if connected else st.warning)(message)

        if clear_col.button("Clear key"):
            st.session_state["wallex_api_key"] = ""
            st.session_state["wallex_api_key_input"] = ""
            st.session_state["wallex_status"] = "Not connected"
            st.session_state["wallex_status_message"] = "The session key was cleared."
            st.info(st.session_state["wallex_status_message"])

        status = st.session_state["wallex_status"]
        if status == "Connected":
            st.success(st.session_state["wallex_status_message"])
        elif status == "Connection failed":
            st.warning(st.session_state["wallex_status_message"])
        else:
            st.info(st.session_state["wallex_status_message"])

        st.selectbox(
            t("app.language", language),
            ["en", "fa"],
            index=0 if language == "en" else 1,
            key="lang_select",
        )
        if st.button("Refresh", type="primary"):
            st.rerun()

    language = st.session_state.get("lang_select", language)
    runtime_settings = build_runtime_settings(
        base_settings,
        st.session_state.get("wallex_api_key"),
    )

    try:
        market_stats = get_market_stats(runtime_settings)
    except Exception:
        st.error("Unable to load public market data. Check your connection and try again.")
        market_stats = []

    if runtime_settings.has_wallex_key:
        try:
            balances = get_portfolio_balances(runtime_settings)
        except Exception:
            st.error("Unable to load account balances. Check the key permissions and try again.")
            balances = []
    else:
        balances = []
        st.warning("No Wallex API key is configured for this session. Enter one in the sidebar to load balances.")

    total_value = value_portfolio(balances, market_stats)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total portfolio value", format_money(total_value, language))
    with col2:
        st.metric("Assets tracked", str(len(balances)))
    with col3:
        st.metric("Market symbols", str(len(market_stats)))

    tab_overview, tab_balances, tab_analysis, tab_buy = st.tabs(
        [
            t("tab.overview", language),
            t("tab.balances", language),
            t("tab.analysis", language),
            "BUY Opportunities",
        ]
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
            st.dataframe(_build_table_rows(balances, market_stats), use_container_width=True)

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
        st.write(analysis_result or t("analysis.empty", language))

    with tab_buy:
        st.write(
            "Scan the highest-volume TMN markets for potential bullish setups "
            "using daily technical indicators."
        )

        st.warning(
            "This is a read-only, rule-based scanner. Its confidence score "
            "is a heuristic ranking, not a probability of profit. "
            "It does not execute trades."
        )

        if st.button("Scan for BUY Opportunities", type="primary"):
            try:
                with st.spinner("Scanning Wallex markets. This may take a while..."):
                    opportunities, market_context = get_buy_opportunities_with_context(
                        settings=runtime_settings,
                        min_confidence=60,
                        max_markets=20,
                    )

                st.session_state["buy_opportunities"] = opportunities
                st.session_state["buy_market_context"] = market_context
                st.session_state["buy_scan_error"] = None

            except Exception as exc:
                st.session_state["buy_scan_error"] = (
                    f"Scanning failed: {type(exc).__name__}: {exc}"
                )

        scan_error = st.session_state.get("buy_scan_error")
        if scan_error:
            st.error(scan_error)

        market_context = st.session_state.get("buy_market_context")

        if market_context is not None:
            st.subheader("Overall Market Conditions")

            col1, col2, col3, col4, col5 = st.columns(5)

            breadth = (
                f"{market_context.breadth:.1%}"
                if market_context.breadth is not None
                else "N/A"
            )

            col1.metric(
                "Overall Risk",
                market_context.risk_condition.replace("_", " ").title(),
            )
            col2.metric(
                "Bitcoin Direction",
                market_context.btc_direction.title(),
            )
            col3.metric("Bullish Breadth", breadth)
            col4.metric(
                "Volatility",
                market_context.volatility.title(),
            )
            col5.metric(
                "Markets Analyzed",
                market_context.symbols_analyzed,
            )

            st.caption(
                "Market context is calculated from the 20 most liquid TMN "
                "markets with sufficient daily history. Bullish breadth "
                "excludes neutral-trend markets."
            )

        opportunities = st.session_state.get("buy_opportunities")

        if opportunities is not None:
            if not opportunities:
                st.info("No qualifying BUY opportunities were found.")
            else:
                st.success(
                    f"Found {len(opportunities)} potential BUY opportunities."
                )

                rows = [
                    {
                        "Symbol": item.symbol,
                        "Price (TMN)": f"{item.price:,.2f}",
                        "Entry range (TMN)": (
                            f"{item.entry_low:,.2f} – {item.entry_high:,.2f}"
                        ),
                        "Stop loss": (
                            f"{item.stop_loss:,.2f}"
                            if item.stop_loss is not None else "N/A"
                        ),
                        "Target 1": (
                            f"{item.target_1:,.2f}"
                            if item.target_1 is not None else "N/A"
                        ),
                        "Target 2": (
                            f"{item.target_2:,.2f}"
                            if item.target_2 is not None else "N/A"
                        ),
                        "Risk/Reward": (
                            f"{item.risk_reward:.2f}"
                            if item.risk_reward is not None else "N/A"
                        ),
                        "Confidence": f"{item.confidence_score:.1f}/100",
                        "Setup": item.opportunity_type,
                    }
                    for item in opportunities
                ]

                st.dataframe(rows, use_container_width=True)

                for item in opportunities:
                    with st.expander(
                        f"{item.symbol} — {item.confidence_score:.1f}/100"
                    ):
                        st.write("**Reasons:**")
                        for reason in item.reasons:
                            st.write(f"- {reason}")

                        st.write("**Invalidation conditions:**")
                        for condition in item.invalidation_conditions:
                            st.write(f"- {condition}")

                        st.write(
                            f"Recommended holding timeframe: "
                            f"{item.recommended_holding_timeframe}"
                        )


if __name__ == "__main__":
    main()