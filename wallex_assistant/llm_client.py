"""LLM client for AI-powered portfolio analysis.

Wraps the OpenAI-compatible API (OpenRouter, etc.) so the rest of the
application can ask for an analysis without knowing the provider details.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

import requests

from .config import get_settings
from .i18n import t

logger = logging.getLogger(__name__)

SUPPORTED_LLM_PROVIDERS = {"mock", "openrouter", "openai", "anthropic", "gemini"}


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
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": t(system, language)},
        {"role": "user", "content": t(user, language, **kwargs)},
    ]
    return messages


def _normalize_provider(provider: str | None) -> str:
    """Return a safe provider key and default to OpenRouter when unknown."""
    normalized = (provider or "openrouter").strip().lower()
    return normalized if normalized in SUPPORTED_LLM_PROVIDERS else "openrouter"


def _provider_url(provider: str) -> str:
    """Map a logical provider name to its default endpoint."""
    mapping = {
        "openrouter": "https://openrouter.ai/api/v1/chat/completions",
        "openai": "https://api.openai.com/v1/chat/completions",
        "anthropic": "https://api.anthropic.com/v1/messages",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
    }
    return mapping.get(provider, "https://openrouter.ai/api/v1/chat/completions")


def _provider_payload(model_name: str, messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """Build the request body for the currently supported OpenAI-compatible path."""
    return {
        "model": model_name,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 1000,
    }


def _portfolio_prompt(
    balances: Iterable[Any],
    market_stats: Iterable[Any],
    *,
    language: str = "en",
) -> str:
    """Build a compact, structured prompt from balances and market stats."""
    portfolio_summary: List[Dict[str, str]] = []
    for bal in balances:
        stat = next(
            (m for m in market_stats if m.symbol.upper() == bal.asset.upper()),
            None,
        )
        price = stat.last_price if stat and stat.last_price is not None else None
        quantity = bal.available + bal.locked
        value = quantity * price if price is not None else None
        portfolio_summary.append(
            {
                "asset": bal.asset,
                "quantity": str(quantity),
                "price": str(price) if price is not None else "N/A",
                "value_tmn": str(value) if value is not None else "N/A",
            }
        )

    total_value = Decimal("0")
    for bal in balances:
        stat = next(
            (m for m in market_stats if m.symbol.upper() == bal.asset.upper()),
            None,
        )
        if stat is None or stat.last_price is None:
            continue
        total_value += (bal.available + bal.locked) * stat.last_price

    lines = [
        f"{t('analysis.run', language)}\n",
        f"Total portfolio value: {total_value}\n",
        "Holdings:\n",
    ]
    for entry in portfolio_summary:
        lines.append(
            f"- {entry['asset']}: {entry['quantity']} @ {entry['price']} "
            f"= {entry['value_tmn']} TMN\n"
        )
    lines.append(f"\n{t('analysis.disclaimer', language)}\n")
    return "".join(lines)


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
    provider_name = _normalize_provider(settings.llm_provider)
    model_name = model or settings.llm_provider or "mock"

    if not model_name or model_name == "mock":
        return _deterministic_summary(balances, market_stats, language=language)

    if provider_name not in {"mock", "openrouter"}:
        logger.warning(
            "LLM provider %r is not yet implemented; using deterministic summary instead.",
            provider_name,
        )
        return _deterministic_summary(balances, market_stats, language=language)

    if not settings.llm_api_key:
        logger.warning(
            "LLM API key is not configured; using deterministic portfolio summary instead."
        )
        return _deterministic_summary(balances, market_stats, language=language)

    user_prompt = _portfolio_prompt(balances, market_stats, language=language)
    messages = _build_messages("portfolio_analysis_system", user_prompt, language=language)
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = _provider_payload(model_name, messages)

    try:
        resp = requests.post(
            _provider_url(provider_name),
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
    lines: List[str] = []
    lines.append(t("analysis.run", language))
    lines.append("")

    assets_with_price: List[Dict[str, Any]] = []
    assets_no_price: List[str] = []

    for bal in balances:
        stat = next(
            (m for m in market_stats if m.symbol.upper() == bal.asset.upper()),
            None,
        )
        if stat and stat.last_price is not None:
            quantity = bal.available + bal.locked
            price = stat.last_price
            assets_with_price.append(
                {
                    "asset": bal.asset,
                    "quantity": float(quantity),
                    "price": float(price),
                    "value": float(quantity * price),
                }
            )
        else:
            assets_no_price.append(bal.asset)

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
