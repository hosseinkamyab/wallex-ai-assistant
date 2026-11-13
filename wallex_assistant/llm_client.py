"""LLM client for AI-powered portfolio analysis.

Wraps the OpenAI-compatible API (OpenRouter, etc.) so the rest of the
application can ask for an analysis without knowing the provider details.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import requests

from .config import get_settings, mask_secret

logger = logging.getLogger(__name__)


def _build_messages(
    system: str,
    user: str,
    *,
    language: str = "en",
    **kwargs: object,
) -> List[Dict[str, str]]:
    """Construct the message list for the LLM call.

    Missing translations fall back: requested language -> English -> the key.
    """
    from .i18n import t

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": t(system, language)},
        {"role": "user", "content": t(user, language, **kwargs)},
    ]
    return messages


def analyze_portfolio(
    balances: list,
    market_stats: list,
    *,
    language: str = "en",
    model: Optional[str] = None,
) -> str:
    """Ask an LLM to generate a portfolio analysis.

    Args:
        balances: list of Balance objects from the account client.
        market_stats: list of MarketStat objects from the market client.
        language: "en" or "fa" for Persian.
        model: Optional model override. Falls back to Settings.llm_provider.

    Returns:
        The LLM's response text (safe to display; no secret data is sent).
    """
    settings = get_settings()
    model_name = model or settings.llm_provider

    if not model_name or model_name == "mock":
        # Deterministic summary when no LLM is configured.
        return _deterministic_summary(balances, market_stats, language=language)

    api_key = settings.llm_api_key
    base_url = settings.wallex_base_url  # reused as a generic base if needed

    # Build the prompt data.
    # We send only what's needed: asset, available quantity, current price, value.
    portfolio_summary: List[Dict[str, str]] = []
    for bal in balances:
        # Find matching market stat
        stat = next(
            (m for m in market_stats if m.symbol.upper() == bal.asset.upper()),
            None,
        )
        price = stat.last_price if stat and stat.last_price else None
        value = (bal.available + bal.locked) * price if price else None
        portfolio_summary.append(
            {
                "asset": bal.asset,
                "quantity": str(bal.available),
                "price": str(price) if price else "N/A",
                "value_tmn": str(value) if value is not None else "N/A",
            }
        )

    total_value = sum(
        (b.available + b.locked)
        * next(
            (m.last_price for m in market_stats if m.symbol.upper() == b.asset.upper()),
            0 or None,
        ) or 0
        for b in balances
    )

    user_prompt = (
        f"{t('analysis.run', language)}\n\n"
        f"Total portfolio value: {total_value}\n\n"
        f"Holdings:\n"
    )
    for entry in portfolio_summary:
        user_prompt += (
            f"- {entry['asset']}: {entry['quantity']} @ {entry['price']} "
            f"= {entry['value_tmn']} TMN\n"
        )

    user_prompt += (
        f"\n{t('analysis.disclaimer', language)}\n"
    )

    messages = _build_messages(
        "portfolio_analysis_system",
        user_prompt,
        language=language,
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 1000,
    }

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=settings.request_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data.get("choices", [{}])[0]
        text = choice.get("message", {}).get("content", "")
        return text.strip() if text else "(no response from LLM)"
    except requests.RequestException as exc:
        logger.error("LLM request failed: %s", exc)
        return f"{t('error.api', language)}: {exc}"


def _deterministic_summary(
    balances: list,
    market_stats: list,
    *,
    language: str = "en",
) -> str:
    """Produce a simple text summary without calling an LLM."""

    from .i18n import t

    lines: List[str] = []
    lines.append(t("analysis.run", language))
    lines.append("")

    # Group by asset performance
    assets_with_price: List[Dict[str, Any]] = []
    assets_no_price: List[str] = []

    for bal in balances:
        stat = next(
            (m for m in market_stats if m.symbol.upper() == bal.asset.upper()),
            None,
        )
        if stat and stat.last_price:
            assets_with_price.append(
                {
                    "asset": bal.asset,
                    "quantity": float(bal.available + bal.locked),
                    "price": float(stat.last_price),
                    "value": float((bal.available + bal.locked) * stat.last_price),
                }
            )
        else:
            assets_no_price.append(bal.asset)

    # Sort by value descending
    assets_with_price.sort(key=lambda x: x["value"], reverse=True)

    total = sum(a["value"] for a in assets_with_price)

    lines.append(f"Total portfolio value: {total:.2f} TMN")
    lines.append("")

    if assets_with_price:
        lines.append(f"{t('portfolio.total_value', language)}:")
        for a in assets_with_price:
            lines.append(
                f"  {a['asset']}: {a['quantity']:.4f} @ {a['price']:.2f} = {a['value']:.2f} TMN"
            )
    else:
        lines.append(t("portfolio.empty", language))

    if assets_no_price:
        lines.append("")
        lines.append(f"(no market data for: {', '.join(assets_no_price)})")

    lines.append("")
    lines.append(t("analysis.disclaimer", language))

    return "\n".join(lines)