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
)


def build_runtime_settings(
    base_settings: Settings,
    api_key: str | None = None,
) -> Settings:
    """Return settings using the active key from Streamlit session state."""
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
    """Validate an API key with one safe read-only account request."""
    cleaned = (api_key or "").strip()
    if not cleaned:
        return (
            False,
            "No Wallex API key has been entered. Add it in the sidebar before "
            "loading account data.",
        )

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
        return (
            False,
            "Wallex rejected the API key. Check that it is valid, active, and "
            "allowed to access read-only account data.",
        )
    except WallexRateLimitError as exc:
        retry_seconds = getattr(exc, "retry_after", None)
        if retry_seconds is not None:
            return (
                False,
                f"Wallex rate-limited the request. Please wait {retry_seconds} "
                "seconds and try again.",
            )
        return (
            False,
            "Wallex rate-limited the request. Please wait a moment and try again.",
        )
    except WallexNetworkError:
        return (
            False,
            "The app could not reach Wallex. Check your network connection and "
            "try again.",
        )
    except WallexNotFoundError:
        return (
            False,
            "The Wallex account endpoint could not be found. Check the base URL.",
        )
    except WallexResponseError:
        return (
            False,
            "Wallex responded, but the payload format was unexpected. Please try "
            "again or refresh the app.",
        )
    except WallexAPIError as exc:
        detail = getattr(exc, "message", str(exc)) or str(exc)
        return False, f"Wallex returned an API error: {detail}"
    except Exception:
        return (
            False,
            "An unexpected validation error occurred. Please try again in a moment.",
        )
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
    """Render the portfolio dashboard."""
    base_settings = get_settings()
    lang = base_settings.language if base_settings.language in {"en", "fa"} else "en"

    st.set_page_config(page_title="Wallex AI Assistant", page_icon="📊", layout="wide")
    st.title(t("app.title", lang))
    st.caption(t("app.subtitle", lang))
    st.info(t("app.readonly_notice", lang))

    st.session_state.setdefault("wallex_api_key", "")
    st.session_state.setdefault("wallex_api_key_input", st.session_state["wallex_api_key"])
    st.session_state.setdefault("wallex_status", "Not connected")
    st.session_state.setdefault(
        "wallex_status_message",
        "No Wallex API key saved in this browser session yet.",
    )

    with st.sidebar:
        st.subheader("API Configuration")
        st.caption(
            "This key is stored only in Streamlit session state and is cleared when "
            "the browser session ends. It is not saved to source files or a local "
            "config file.",
        )

        show_key = st.checkbox("Show API key", value=False, key="show_wallex_api_key")
        key_input_type = "default" if show_key else "password"
        st.text_input(
            "Wallex API key",
            value=st.session_state.get("wallex_api_key_input", ""),
            type=key_input_type,
            key="wallex_api_key_input",
        )

        save_col, clear_col = st.columns(2)
        if save_col.button("Save & Connect", type="primary"):
            entered = st.session_state.get("wallex_api_key_input", "").strip()
            if not entered:
                st.session_state["wallex_api_key"] = ""
                st.session_state["wallex_status"] = "Not connected"
                st.session_state["wallex_status_message"] = (
                    "No Wallex API key was entered. Add one before loading account data."
                )
                st.warning(st.session_state["wallex_status_message"])
            else:
                st.session_state["wallex_api_key"] = entered
                ok, msg = validate_wallex_api_key(
                    entered,
                    base_url=base_settings.wallex_base_url,
                    timeout=base_settings.request_timeout,
                    max_retries=base_settings.max_retries,
                )
                st.session_state["wallex_status"] = (
                    "Connected" if ok else "Connection failed"
                )
                st.session_state["wallex_status_message"] = msg
                if ok:
                    st.success(msg)
                else:
                    st.warning(msg)

        if clear_col.button("Clear key"):
            st.session_state["wallex_api_key"] = ""
            st.session_state["wallex_api_key_input"] = ""
            st.session_state["wallex_status"] = "Not connected"
            st.session_state["wallex_status_message"] = (
                "The saved Wallex API key was cleared. Enter a new one to reconnect."
            )
            st.info(st.session_state["wallex_status_message"])

        status = st.session_state.get("wallex_status", "Not connected")
        if status == "Connected":
            st.success(st.session_state.get("wallex_status_message", status))
        elif status == "Connection failed":
            st.warning(st.session_state.get("wallex_status_message", status))
        else:
            st.info(st.session_state.get("wallex_status_message", status))

        st.selectbox(
            t("app.language", lang),
            ["en", "fa"],
            index=0 if lang == "en" else 1,
            key="lang_select",
        )
        if st.button("Refresh", type="primary"):
            st.rerun()

    lang = st.session_state.get("lang_select", lang)
    runtime_settings = build_runtime_settings(
        base_settings,
        st.session_state.get("wallex_api_key"),
    )

    try:
        market_stats = get_market_stats(runtime_settings)
    except Exception as exc:  # pragma: no cover - UI path
        st.error(f"Unable to load market data: {exc}")
        market_stats = []

    if runtime_settings.has_wallex_key:
        try:
            balances = get_portfolio_balances(runtime_settings)
        except Exception as exc:  # pragma: no cover - UI path
            st.error(f"Unable to load account balances: {exc}")
            balances = []
    else:
        balances = []
        st.warning(
            "No Wallex API key is configured for this session. "
            "Enter one in the sidebar to load live account balances and account data."
        )

    total_value = value_portfolio(balances, market_stats)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total portfolio value", format_money(total_value, lang))
    with col2:
        st.metric("Assets tracked", str(len(balances)))
    with col3:
        st.metric("Market symbols", str(len(market_stats)))

    tab_overview, tab_balances, tab_analysis = st.tabs(
        [t("tab.overview", lang), t("tab.balances", lang), t("tab.analysis", lang)]
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
            st.info(t("portfolio.empty", lang))
        else:
            rows = _build_table_rows(balances, market_stats)
            st.dataframe(rows, use_container_width=True)

    with tab_analysis:
        if st.button(t("analysis.run", lang), type="primary"):
            with st.spinner(t("analysis.running", lang)):
                analysis = generate_analysis(
                    balances=balances,
                    market_stats=market_stats,
                    language=lang,
                )
            st.session_state["analysis_result"] = analysis

        analysis_result = st.session_state.get("analysis_result")
        if analysis_result:
            st.write(analysis_result)
        else:
            st.write(t("analysis.empty", lang))


if __name__ == "__main__":
    main()
