"""Deterministic diagnostics for empty BUY opportunity scans.

The diagnostics mirror the existing BuyOpportunityScanner rules. They do not
change, weaken, or recommend changes to those rules.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from wallex_assistant.analysis import calculate_indicators
from wallex_assistant.buy_opportunity import (
    _entry_range,
    _compute_risk_reward,
    _confidence_score,
    _stop_and_targets,
    _support_resistance,
    _valid_candles,
)


def diagnose_buy_rejections(
    symbols: Sequence[str],
    history_by_symbol: Mapping[str, Mapping[str, Sequence[Any]]],
    *,
    min_confidence: float = 60.0,
    min_volume_ratio: float = 1.2,
    min_risk_reward: float = 1.3,
    max_candle_age_days: float | None = 3,
) -> dict[str, Any]:
    """Return rule-by-rule rejection counts and the affected symbols."""
    counts: Counter[str] = Counter()
    symbols_by_reason: dict[str, list[str]] = {}

    history_index = {
        str(key).upper().replace("/", "").replace("-", "").replace(" ", ""): value
        for key, value in history_by_symbol.items()
    }

    for requested_symbol in symbols:
        symbol = str(requested_symbol).upper().replace("/", "").replace("-", "").replace(" ", "")
        history = history_index.get(symbol)

        def reject(code: str) -> None:
            counts[code] += 1
            symbols_by_reason.setdefault(code, [])
            if symbol not in symbols_by_reason[code]:
                symbols_by_reason[code].append(symbol)

        if not history:
            reject("insufficient_history")
            continue

        raw_candles = history.get("1d", [])
        candles = _valid_candles(raw_candles)
        if len(candles) < 50:
            reject("insufficient_history")
            continue

        latest = getattr(candles[-1], "open_time", None)
        if max_candle_age_days is not None:
            if not isinstance(latest, datetime):
                reject("stale_data")
                continue
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - latest.astimezone(timezone.utc)).total_seconds() / 86400
            if age > max_candle_age_days or age < -1:
                reject("stale_data")
                continue

        try:
            daily = calculate_indicators(candles)
        except (TypeError, ValueError, ArithmeticError):
            reject("technical_data_unavailable")
            continue

        price = _diagnostic_float(daily.get("close"))
        rsi = _diagnostic_float(daily.get("rsi_14"))
        macd = _diagnostic_float(daily.get("macd"))
        macd_signal = _diagnostic_float(daily.get("macd_signal"))
        atr = _diagnostic_float(daily.get("atr_14"))
        trend = daily.get("trend")

        if price is None or price <= 0 or trend != "bullish" or rsi is None or macd is None or macd_signal is None or atr is None or atr <= 0:
            if trend != "bullish" and trend is not None:
                reject("no_bullish_trend")
            else:
                reject("technical_data_unavailable")
            continue

        support, resistance = _support_resistance(candles)
        if support is None or resistance is None or support <= 0 or resistance <= 0:
            reject("levels_unavailable")
            continue

        if rsi < 25 or rsi > 70:
            reject("entry_rsi_not_confirmed")
            continue

        volume_ratio = _diagnostic_float(daily.get("volume_vs_20_period"))
        volume_ok = volume_ratio is not None and volume_ratio >= min_volume_ratio
        recovery = rsi < 40 and macd >= macd_signal
        if not volume_ok and not recovery:
            reject("volume_not_confirmed")
            continue

        near_support = (price - support) / price <= 0.04 and price > support
        breakout = resistance < price and macd > macd_signal and volume_ok
        if breakout:
            opportunity_type = "breakout opportunities"
        elif near_support and rsi < 60:
            opportunity_type = "support-level rebounds"
        elif rsi >= 40 and macd >= macd_signal:
            opportunity_type = "trend-following entries"
        else:
            reject("entry_condition_not_satisfied")
            continue

        entry_low, entry_high = _entry_range(
            opportunity_type=opportunity_type,
            price=price,
            support=support,
            resistance=resistance,
        )
        stop, target_1, target_2 = _stop_and_targets(
            price=price,
            support=support,
            resistance=resistance,
            opportunity_type=opportunity_type,
            atr=atr,
            entry_low=entry_low,
            entry_high=entry_high,
        )
        risk_reward = _compute_risk_reward(entry_high, stop, target_1, target_2)

        if not (0 < stop < entry_low <= entry_high < target_1 <= target_2):
            reject("risk_reward_levels_invalid")
            continue
        if risk_reward < min_risk_reward:
            reject("risk_reward_too_low")
            continue

        liquidity_score = 0.7
        confidence = _confidence_score(
            trend_score=1.0,
            momentum_score=0.8 if 40 <= rsi <= 60 else 0.6,
            volume_score=1.0 if volume_ok else 0.5,
            liquidity_score=liquidity_score,
            risk_reward=risk_reward,
            market_env=1.0,
        )
        if confidence < min_confidence:
            reject("confidence_below_threshold")

    return {
        "counts": dict(counts),
        "symbols_by_reason": symbols_by_reason,
        "rejected_markets": sum(counts.values()),
    }


def _diagnostic_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if _is_finite(number) else None


def _is_finite(value: float) -> bool:
    import math
    return math.isfinite(value)


REASON_LABELS = {
    "insufficient_history": "Insufficient historical data",
    "stale_data": "Historical data is stale",
    "technical_data_unavailable": "Technical indicator data is incomplete",
    "no_bullish_trend": "Daily bullish trend confirmation is absent",
    "levels_unavailable": "Valid support and resistance levels could not be established",
    "entry_rsi_not_confirmed": "The RSI entry range is not satisfied",
    "volume_not_confirmed": "Bullish volume or recovery confirmation is weak",
    "entry_condition_not_satisfied": "A breakout, support rebound, or trend-following entry condition is not satisfied",
    "risk_reward_levels_invalid": "A valid stop-loss and target structure could not be established",
    "risk_reward_too_low": "Risk/reward is below the scanner threshold",
    "confidence_below_threshold": "Heuristic confidence is below 60/100",
}


def market_condition_explanation(context: Any) -> str:
    btc = str(getattr(context, "btc_direction", "unknown")).lower()
    breadth = getattr(context, "breadth", None)
    volatility = str(getattr(context, "volatility", "unknown")).lower()
    risk = str(getattr(context, "risk_condition", "unknown")).lower()

    if btc == "bearish" and breadth is not None and breadth < 0.3:
        return "The broader environment is unfavorable: Bitcoin is bearish and only a small share of analyzed markets is bullish."
    if btc == "bearish" and breadth is not None:
        return "Bitcoin is bearish, so even some market-level strength may not be enough to support a qualified BUY setup."
    if btc == "bullish" and breadth is not None and breadth < 0.3:
        return "Bitcoin is bullish, but participation is limited because only a small share of analyzed markets is bullish."
    if btc == "bullish" and breadth is not None:
        return "Bitcoin and market participation are broadly constructive, so markets that fail are more likely missing a technical or risk/reward requirement."
    if volatility == "high":
        return "Volatility is elevated, making price swings larger and reducing the confidence of existing setups."
    if risk == "elevated":
        return "The overall risk level is elevated under the scanner's existing market-context rules."
    return "The wider market does not currently provide enough evidence for a qualified BUY setup."


def watch_next_explanation(context: Any) -> str:
    btc = str(getattr(context, "btc_direction", "unknown")).lower()
    breadth = getattr(context, "breadth", None)
    volatility = str(getattr(context, "volatility", "unknown")).lower()

    conditions = []
    if btc != "bullish":
        conditions.append("Bitcoin moving back toward a bullish daily direction")
    if breadth is None or breadth < 0.5:
        conditions.append("a higher share of markets confirming a bullish trend")
    if volatility == "high":
        conditions.append("market volatility moving back to a manageable level")
    conditions.extend([
        "clearer bullish technical confirmation, such as EMA, RSI, MACD, and volume alignment",
        "valid entry levels with a stop-loss and risk/reward ratio that meet the existing rules",
    ])
    return "; ".join(conditions[:3]) + "."


__all__ = ["diagnose_buy_rejections", "market_condition_explanation", "watch_next_explanation", "REASON_LABELS"]
