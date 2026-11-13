"""Portfolio valuation and AI analysis.

Ties together account balances + market prices, calculates total value in TMN,
and can generate AI-powered insights via an LLM.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from .account_client import AccountClient, Balance
from .config import Settings, get_settings
from .market_client import MarketClient, MarketStat


def get_portfolio_balances(
    settings: Settings | None = None,
) -> list[Balance]:
    """Get non-empty balances for the configured account."""
    settings = settings or get_settings()
    if not settings.has_wallex_key:
        return []
    client = AccountClient.from_settings(settings)
    try:
        return client.get_balances()
    finally:
        client.close()


def get_market_stats(
    settings: Settings | None = None,
) -> list[MarketStat]:
    """Get latest market stats for all tradeable symbols."""
    settings = settings or get_settings()
    client = MarketClient.from_settings(settings)
    try:
        return client.get_market_stats()
    finally:
        client.close()


def value_portfolio(
    balances: list[Balance],
    market_stats: list[MarketStat],
) -> Decimal:
    """Calculate total portfolio value in TMN.

    Uses Decimal throughout to avoid float precision loss.
    """
    total = Decimal("0")
    for bal in balances:
        stat = next(
            (m for m in market_stats if m.symbol.upper() == bal.asset.upper()),
            None,
        )
        if stat is None or stat.last_price is None:
            continue
        holding = bal.available + bal.locked
        total += holding * stat.last_price
    return total


def get_asset_values(
    balances: list[Balance],
    market_stats: list[MarketStat],
) -> list[Dict[str, Any]]:
    """Return per-asset value breakdown as dicts.

    Each dict: {asset, quantity, price, value_tmn}
    """
    result: list[Dict[str, Any]] = []
    for bal in balances:
        stat = next(
            (m for m in market_stats if m.symbol.upper() == bal.asset.upper()),
            None,
        )
        price = stat.last_price if stat else None
        holding = bal.available + bal.locked
        value = holding * price if price is not None else Decimal("0")
        result.append(
            {
                "asset": bal.asset,
                "quantity": str(holding),
                "price": str(price) if price is not None else "N/A",
                "value_tmn": str(value),
            }
        )

    def sort_key(entry: Dict[str, Any]) -> Decimal:
        value_tmn = entry["value_tmn"]
        if value_tmn == "N/A":
            return Decimal("0")
        try:
            return Decimal(str(value_tmn))
        except Exception:
            return Decimal("0")

    result.sort(key=sort_key, reverse=True)
    return result


def generate_analysis(
    balances: list[Balance] | None = None,
    market_stats: list[MarketStat] | None = None,
    *,
    language: str = "en",
    model: str | None = None,
) -> str:
    """Generate a portfolio analysis, either AI or deterministic.

    If an LLM model is configured (via Settings.llm_provider), delegates to
    the LLM client. Otherwise returns a deterministic summary.
    """
    settings = get_settings()

    if balances is None:
        balances = get_portfolio_balances(settings)
    if market_stats is None:
        market_stats = get_market_stats(settings)

    if not balances:
        from .i18n import t

        return t("analysis.empty", language)

    from .llm_client import analyze_portfolio

    return analyze_portfolio(balances, market_stats, language=language, model=model)
