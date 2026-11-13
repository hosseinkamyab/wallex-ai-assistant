from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

import numpy as np

from wallex_assistant.analysis import calculate_indicators


@dataclass
class BuyOpportunity:
    """Structured buy idea with risk parameters and ranking metadata."""

    symbol: str
    name: str
    pair: str
    price: float
    entry_low: float
    entry_high: float
    trend: str
    opportunity_type: str
    reasons: list[str] = field(default_factory=list)
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    volume_confirmation: bool = False
    support: float | None = None
    resistance: float | None = None
    stop_loss: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    potential_upside_pct: float | None = None
    potential_downside_pct: float | None = None
    risk_reward: float | None = None
    confidence_score: float = 0.0
    recommended_holding_timeframe: str = "1-6 weeks"
    invalidation_conditions: list[str] = field(default_factory=list)
    market_condition: str = "constructive"

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "cryptocurrency": self.name,
            "pair": self.pair,
            "current_price": self.price,
            "entry_price": {"low": self.entry_low, "high": self.entry_high},
            "trend": self.trend,
            "type": self.opportunity_type,
            "technical_reasons": self.reasons,
            "rsi_14": self.rsi_14,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "macd_histogram": self.macd_histogram,
            "volume_confirmation": self.volume_confirmation,
            "support": self.support,
            "resistance": self.resistance,
            "suggested_stop_loss": self.stop_loss,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "potential_upside_pct": self.potential_upside_pct,
            "potential_downside_pct": self.potential_downside_pct,
            "risk_reward": self.risk_reward,
            "confidence_score": round(float(self.confidence_score), 1),
            "recommended_holding_timeframe": self.recommended_holding_timeframe,
            "invalidation_conditions": self.invalidation_conditions,
            "market_condition": self.market_condition,
        }


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError, InvalidOperation):
        return None


def _normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("USDT", "TMN").replace("/", "").replace("-", "")


def _symbol_name(symbol: str) -> str:
    aliases = {
        "BTCTMN": "Bitcoin",
        "ETHTMN": "Ethereum",
        "SOLTMN": "Solana",
        "XRPTMN": "XRP",
        "ADATMN": "Cardano",
        "DOTTMN": "Polkadot",
        "LINKTMN": "Chainlink",
        "AVAXTMN": "Avalanche",
        "DOGETMN": "Dogecoin",
        "TRXTMN": "TRON",
        "BNBTMN": "BNB",
    }
    return aliases.get(_normalize_symbol(symbol), _normalize_symbol(symbol).replace("TMN", ""))


def _support_resistance(values: Sequence[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    data = np.asarray(values, dtype=float)
    if data.size < 2:
        return float(data[0]), float(data[0])
    window = data[-50:] if data.size >= 50 else data
    support = float(np.min(window))
    resistance = float(np.max(window))
    return support, resistance


def _compute_risk_reward(entry: float, stop_loss: float, target_1: float, target_2: float) -> float:
    if entry <= 0 or stop_loss <= 0:
        return 0.0
    downside = abs(entry - stop_loss) / entry
    if downside == 0:
        return 0.0
    upside = (abs(target_1 - entry) + abs(target_2 - entry)) / (2 * entry)
    return round(float(upside / downside), 2)


def _opportunity_type(
    *,
    trend: str,
    rsi: float | None,
    macd: float | None,
    macd_signal: float | None,
    price: float,
    support: float | None,
    resistance: float | None,
    volume_ok: bool,
) -> str:
    if (
        trend == "bullish"
        and support is not None
        and price > support
        and rsi is not None
        and 40 <= rsi <= 60
        and macd is not None
        and macd_signal is not None
        and macd >= macd_signal
    ):
        return "trend-following entries"

    if (
        trend == "bullish"
        and support is not None
        and price <= support * 1.02
        and rsi is not None
        and rsi < 60
    ):
        return "support-level rebounds"

    if (
        trend == "bullish"
        and rsi is not None
        and 35 <= rsi <= 55
        and resistance is not None
        and price < resistance * 0.98
    ):
        return "pullback opportunities"

    if (
        volume_ok
        and resistance is not None
        and price >= resistance * 0.995
        and macd is not None
        and macd_signal is not None
        and macd > macd_signal
    ):
        return "breakout opportunities"

    if (
        rsi is not None
        and rsi < 35
        and macd is not None
        and macd_signal is not None
        and macd >= macd_signal
    ):
        return "oversold recovery opportunities"

    if trend == "bullish" and support is not None and price <= support * 1.08 and volume_ok:
        return "long-term accumulation opportunities"

    return "no-opportunity"


def _entry_range(
    *,
    opportunity_type: str,
    price: float,
    support: float | None,
    resistance: float | None,
) -> tuple[float, float]:
    if opportunity_type == "pullback opportunities":
        low = min(price, (support or price) * 1.02)
        high = max(price, (support or price) * 1.05)
        return low, high
    if opportunity_type in {"support-level rebounds", "long-term accumulation opportunities"}:
        low = min(price, (support or price) * 1.02)
        high = max(price, (support or price) * 1.08)
        return low, high
    if opportunity_type == "breakout opportunities":
        low = max(price * 0.995, (resistance or price) * 0.995)
        high = min(price * 1.01, (resistance or price) * 1.01)
        return low, high
    return price * 0.99, price * 1.01


def _stop_and_targets(*, price: float, support: float | None, resistance: float | None, opportunity_type: str) -> tuple[float, float, float]:
    stop = support * 0.96 if support is not None else price * 0.94
    if opportunity_type == "breakout opportunities":
        target_1 = (resistance or price) * 1.04
        target_2 = (resistance or price) * 1.10
    elif opportunity_type in {"support-level rebounds", "long-term accumulation opportunities"}:
        target_1 = (support or price) * 1.12
        target_2 = (support or price) * 1.22
    else:
        target_1 = price * 1.08
        target_2 = price * 1.18
    return stop, target_1, target_2


def _confidence_score(
    *,
    trend_score: float,
    momentum_score: float,
    volume_score: float,
    liquidity_score: float,
    risk_reward: float,
    market_env: float,
) -> float:
    raw = (
        0.28 * trend_score
        + 0.22 * momentum_score
        + 0.20 * volume_score
        + 0.15 * liquidity_score
        + 0.10 * risk_reward
        + 0.05 * market_env
    )
    return float(np.clip(raw * 100, 0, 100))


def _build_reasons(
    *,
    trend: str,
    rsi: float | None,
    macd: float | None,
    macd_signal: float | None,
    volume_ratio: float | None,
    support: float | None,
    resistance: float | None,
    opportunity_type: str,
) -> list[str]:
    reasons: list[str] = []
    if trend == "bullish":
        reasons.append("Daily trend is constructive and the market structure is intact.")
    if rsi is not None:
        reasons.append(f"RSI(14) is {rsi:.1f}; the reading is not yet extreme enough to justify automatic selling.")
    if macd is not None and macd_signal is not None:
        direction = "above" if macd > macd_signal else "below"
        reasons.append(f"MACD is {direction} its signal line, supporting momentum confirmation.")
    if volume_ratio is not None:
        reasons.append(f"Volume is {volume_ratio:.1f}x its 20-period average, supporting the setup.")
    if support is not None:
        reasons.append(f"The price is holding above support near {support:.4f}.")
    if resistance is not None:
        reasons.append(f"The market is testing resistance around {resistance:.4f}.")
    reasons.append(f"Opportunity type: {opportunity_type}.")
    return reasons


def _invalidation_conditions(
    *,
    opportunity_type: str,
    support: float | None,
    resistance: float | None,
    trend: str,
) -> list[str]:
    invalidations = [
        "A sustained close below the key support zone invalidates the setup.",
        "If the 21/50 EMA structure rolls over, the bullish case weakens materially.",
        "If volume collapses and the move loses confirmation, the opportunity is no longer valid.",
    ]
    if opportunity_type == "breakout opportunities":
        invalidations.append("The breakout fails and price rejects the resistance zone.")
    if opportunity_type == "support-level rebounds":
        invalidations.append("Support is broken and the bounce does not hold.")
    if trend == "bearish":
        invalidations.append("The broader trend turns decisively bearish.")
    if support is not None and resistance is not None:
        invalidations.append(f"Price closes below {support:.4f} or above {resistance:.4f} with weak confirmation.")
    return invalidations


class BuyOpportunityScanner:
    def __init__(
        self,
        market_client: Any | None = None,
        *,
        min_confidence: float = 60.0,
        min_volume_ratio: float = 1.2,
        min_liquidity_usd: float = 50000,
        min_risk_reward: float = 1.3,
    ) -> None:
        self.market_client = market_client
        self.min_confidence = min_confidence
        self.min_volume_ratio = min_volume_ratio
        self.min_liquidity_usd = min_liquidity_usd
        self.min_risk_reward = min_risk_reward

    def scan(self, symbols: Sequence[str], history_by_symbol: dict[str, dict[str, list[Any]]]) -> list[BuyOpportunity]:
        opportunities: list[BuyOpportunity] = []
        for symbol in symbols:
            key = symbol.upper()
            if key not in history_by_symbol:
                continue
            history = history_by_symbol.get(key, {})
            if not history:
                continue
            daily = calculate_indicators(history.get("1d", []))
            if daily.get("candles", 0) < 50:
                continue
            chart_close = _safe_float(daily.get("close"))
            if chart_close is None or chart_close <= 0:
                continue

            rsi = _safe_float(daily.get("rsi_14"))
            macd = _safe_float(daily.get("macd"))
            macd_signal = _safe_float(daily.get("macd_signal"))
            trend = daily.get("trend", "neutral")
            if trend == "bearish":
                continue

            close_series = [float(candle.close) for candle in history.get("1d", [])]
            support, resistance = _support_resistance(close_series)
            if support is None or resistance is None:
                continue

            volume_ratio = _safe_float(daily.get("volume_vs_20_period"))
            volume_ok = bool(volume_ratio is not None and volume_ratio >= self.min_volume_ratio)
            if rsi is not None and rsi > 75:
                continue
            if rsi is not None and rsi < 20 and trend != "bullish":
                continue

            if self.market_client is not None:
                try:
                    ticker = self.market_client.get_ticker(symbol)
                    volume_24h = _safe_float(ticker.volume_24h) or _safe_float(ticker.quote_volume_24h) or 0.0
                except Exception:
                    volume_24h = _safe_float(daily.get("volume")) or 0.0
            else:
                volume_24h = _safe_float(daily.get("volume")) or 0.0

            if volume_24h < self.min_liquidity_usd:
                continue

            if not volume_ok and not (
                rsi is not None and rsi < 35 and macd is not None and macd_signal is not None and macd >= macd_signal
            ):
                continue

            opp_type = _opportunity_type(
                trend=trend,
                rsi=rsi,
                macd=macd,
                macd_signal=macd_signal,
                price=chart_close,
                support=support,
                resistance=resistance,
                volume_ok=volume_ok,
            )
            if opp_type == "no-opportunity":
                continue

            entry_low, entry_high = _entry_range(
                opportunity_type=opp_type,
                price=chart_close,
                support=support,
                resistance=resistance,
            )
            stop_loss, target_1, target_2 = _stop_and_targets(
                price=chart_close,
                support=support,
                resistance=resistance,
                opportunity_type=opp_type,
            )
            upside_pct = ((target_1 - chart_close) / chart_close) * 100
            downside_pct = ((chart_close - stop_loss) / chart_close) * 100 if chart_close > stop_loss else 0.0
            risk_reward = _compute_risk_reward(chart_close, stop_loss, target_1, target_2)
            if risk_reward < self.min_risk_reward:
                continue

            trend_score = 1.0 if trend == "bullish" else 0.2
            momentum_score = 0.8 if rsi is not None and 35 <= rsi <= 60 else 0.3
            if rsi is not None and rsi < 35:
                momentum_score = 1.0
            if rsi is not None and rsi > 70:
                momentum_score = 0.1
            volume_score = 1.0 if volume_ok else 0.4
            liquidity_score = 1.0 if volume_24h >= self.min_liquidity_usd * 2 else 0.7
            market_env = 1.0 if trend == "bullish" else 0.2
            confidence = _confidence_score(
                trend_score=trend_score,
                momentum_score=momentum_score,
                volume_score=volume_score,
                liquidity_score=liquidity_score,
                risk_reward=risk_reward,
                market_env=market_env,
            )
            if confidence < self.min_confidence:
                continue

            reasons = _build_reasons(
                trend=trend,
                rsi=rsi,
                macd=macd,
                macd_signal=macd_signal,
                volume_ratio=volume_ratio,
                support=support,
                resistance=resistance,
                opportunity_type=opp_type,
            )
            opportunity = BuyOpportunity(
                symbol=key,
                name=_symbol_name(key),
                pair=f"{key}",
                price=chart_close,
                entry_low=entry_low,
                entry_high=entry_high,
                trend=trend,
                opportunity_type=opp_type,
                reasons=reasons,
                rsi_14=rsi,
                macd=macd,
                macd_signal=macd_signal,
                macd_histogram=(macd - macd_signal) if macd is not None and macd_signal is not None else None,
                volume_confirmation=volume_ok,
                support=support,
                resistance=resistance,
                stop_loss=stop_loss,
                target_1=target_1,
                target_2=target_2,
                potential_upside_pct=round(float(upside_pct), 2),
                potential_downside_pct=round(float(downside_pct), 2),
                risk_reward=risk_reward,
                confidence_score=confidence,
                recommended_holding_timeframe="1-6 weeks" if opp_type not in {"breakout opportunities", "long-term accumulation opportunities"} else "2-12 weeks",
                invalidation_conditions=_invalidation_conditions(
                    opportunity_type=opp_type,
                    support=support,
                    resistance=resistance,
                    trend=trend,
                ),
                market_condition="constructive" if trend == "bullish" else "mixed",
            )
            opportunities.append(opportunity)

        return sorted(opportunities, key=lambda item: (item.confidence_score, item.risk_reward or 0), reverse=True)


def detect_best_buy_opportunity(
    market_client: Any | None,
    symbols: Sequence[str],
    history_by_symbol: dict[str, dict[str, list[Any]]],
) -> list[BuyOpportunity]:
    """Return ranked buy opportunities sorted from most attractive to least attractive."""
    scanner = BuyOpportunityScanner(market_client=market_client)
    return scanner.scan(symbols, history_by_symbol)


def recommend_best_buy(
    market_client: Any | None,
    symbols: Sequence[str],
    history_by_symbol: dict[str, dict[str, list[Any]]],
) -> tuple[str, str | None, list[BuyOpportunity]]:
    """Return BUY or WAIT based on whether any valid opportunities pass the filters."""
    ranked = detect_best_buy_opportunity(market_client, symbols, history_by_symbol)
    if not ranked:
        return "WAIT", None, []
    return "BUY", ranked[0].symbol, ranked


__all__ = [
    "BuyOpportunity",
    "BuyOpportunityScanner",
    "detect_best_buy_opportunity",
    "recommend_best_buy",
]


if __name__ == "__main__":
    print("Buy opportunity detection module ready.")
