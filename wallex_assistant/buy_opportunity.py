from __future__ import annotations

"""Conservative, read-only ranking of potential Wallex BUY setups.

Scores are heuristic evidence rankings, not probabilities or promises of return.
The scanner only consumes public market data and never changes an account.
"""

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import InvalidOperation
from typing import Any, Sequence

from wallex_assistant.analysis import calculate_indicators

logger = logging.getLogger(__name__)


@dataclass
class BuyOpportunity:
    """A read-only market setup with explicit price levels and evidence."""

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
    entry_status: str = "IMMEDIATE"

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation; score is not a probability."""
        return {
            "symbol": self.symbol, "cryptocurrency": self.name, "pair": self.pair,
            "current_price": self.price,
            "entry_price": {"low": self.entry_low, "high": self.entry_high},
            "entry_status": self.entry_status, "trend": self.trend,
            "type": self.opportunity_type, "technical_reasons": self.reasons,
            "rsi_14": self.rsi_14, "macd": self.macd,
            "macd_signal": self.macd_signal, "macd_histogram": self.macd_histogram,
            "volume_confirmation": self.volume_confirmation, "support": self.support,
            "resistance": self.resistance, "suggested_stop_loss": self.stop_loss,
            "target_1": self.target_1, "target_2": self.target_2,
            "potential_upside_pct": self.potential_upside_pct,
            "potential_downside_pct": self.potential_downside_pct,
            "risk_reward": self.risk_reward,
            "confidence_score": round(float(self.confidence_score), 1),
            "confidence_note": "Heuristic evidence ranking, not a probability of success.",
            "recommended_holding_timeframe": self.recommended_holding_timeframe,
            "invalidation_conditions": self.invalidation_conditions,
            "market_condition": self.market_condition,
        }


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, InvalidOperation, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _normalize_symbol(symbol: str) -> str:
    """Normalize separators/case only; never rewrite one quote currency as another."""
    if not isinstance(symbol, str):
        return ""
    normalized = re.sub(r"[\s/_.-]+", "", symbol).upper()
    return normalized if re.fullmatch(r"[A-Z0-9]{4,30}", normalized) else ""


def _symbol_name(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    aliases = {
        "BTCTMN": "Bitcoin", "BTCUSDT": "Bitcoin", "ETHTMN": "Ethereum",
        "ETHUSDT": "Ethereum", "SOLTMN": "Solana", "SOLUSDT": "Solana",
        "XRPTMN": "XRP", "ADATMN": "Cardano", "DOTTMN": "Polkadot",
        "LINKTMN": "Chainlink", "AVAXTMN": "Avalanche", "DOGETMN": "Dogecoin",
        "TRXTMN": "TRON", "BNBTMN": "BNB",
    }
    for quote in ("USDT", "USDC", "TMN", "IRT", "BTC", "ETH"):
        if normalized.endswith(quote) and len(normalized) > len(quote):
            return aliases.get(normalized, normalized[:-len(quote)])
    return aliases.get(normalized, normalized)


def _valid_candles(candles: Sequence[Any]) -> list[Any]:
    """Keep finite, positive OHLC candles sorted by open time and deduplicated."""
    valid: dict[Any, Any] = {}
    for candle in candles:
        try:
            values = [_safe_float(getattr(candle, name)) for name in ("open", "high", "low", "close")]
            stamp = getattr(candle, "open_time")
        except (AttributeError, TypeError):
            continue
        open_price, high, low, close = values
        if (any(value is None for value in values) or min(values) <= 0
                or low > min(open_price, close) or high < max(open_price, close)
                or low > high):
            continue
        volume = _safe_float(getattr(candle, "volume", None))
        if getattr(candle, "volume", None) is not None and (volume is None or volume < 0):
            continue
        valid[stamp] = candle
    try:
        return [valid[key] for key in sorted(valid)]
    except TypeError:
        return []


def _support_resistance(candles: Sequence[Any]) -> tuple[float | None, float | None]:
    """Estimate nearby levels using swing pivots, with window extrema fallback.

    A pivot low/high requires reaction candles on both sides in the latest 50 bars.
    The method is an estimate, not a guaranteed support or resistance zone.
    """
    rows = _valid_candles(candles)[-50:] if candles is not None else []
    if not rows:
        return None, None
    lows = [_safe_float(row.low) for row in rows]
    highs = [_safe_float(row.high) for row in rows]
    close = _safe_float(rows[-1].close)
    if close is None:
        return None, None

    pivot_lows = []
    pivot_highs = []
    for i in range(2, len(rows) - 2):
        left_lows = [value for value in lows[i-2:i] if value is not None]
        right_lows = [value for value in lows[i+1:i+3] if value is not None]
        if lows[i] is not None and left_lows and right_lows:
            if lows[i] <= min(left_lows + right_lows):
                pivot_lows.append(lows[i])
        left_highs = [value for value in highs[i-2:i] if value is not None]
        right_highs = [value for value in highs[i+1:i+3] if value is not None]
        if highs[i] is not None and left_highs and right_highs:
            if highs[i] >= max(left_highs + right_highs):
                pivot_highs.append(highs[i])

    below = [value for value in pivot_lows if value is not None and value < close]
    above = [value for value in pivot_highs if value is not None and value > close]
    valid_lows = [value for value in lows if value is not None]
    valid_highs = [value for value in highs if value is not None]
    support = max(below) if below else min(valid_lows)
    resistance = min(above) if above else max(valid_highs)
    return float(support), float(resistance)


def _compute_risk_reward(entry: float, stop_loss: float, target_1: float, target_2: float) -> float:
    """Return mean target reward divided by entry-to-stop risk."""
    levels = (entry, stop_loss, target_1, target_2)
    if not all(math.isfinite(value) for value in levels):
        return 0.0
    if not (0 < stop_loss < entry < target_1 <= target_2):
        return 0.0
    downside = entry - stop_loss
    reward = ((target_1 - entry) + (target_2 - entry)) / 2
    return round(reward / downside, 2) if downside > 0 else 0.0


def _entry_range(*, opportunity_type: str, price: float, support: float | None,
                 resistance: float | None) -> tuple[float, float]:
    """Return a consistent entry band for immediate or pullback setups."""
    if opportunity_type in {"support-level rebounds", "pullback opportunities"} and support and support < price:
        return support * 0.995, support * 1.015
    if opportunity_type == "breakout opportunities" and resistance:
        return max(price * 0.995, resistance * 0.995), max(price * 1.005, resistance * 1.005)
    return price * 0.995, price * 1.005


def _stop_and_targets(*, price: float, support: float | None, resistance: float | None,
                      opportunity_type: str, atr: float | None = None,
                      entry_low: float | None = None, entry_high: float | None = None
                      ) -> tuple[float, float, float]:
    """Build ATR-aware BUY levels; fall back to a 2% ATR proxy."""
    if not math.isfinite(price) or price <= 0:
        return 0.0, 0.0, 0.0
    entry_low = entry_low if entry_low is not None else price
    entry_high = entry_high if entry_high is not None else price
    volatility = atr if atr is not None and math.isfinite(atr) and atr > 0 else price * 0.02
    stop_candidates = [entry_low - volatility]
    if support is not None and 0 < support < entry_low:
        stop_candidates.append(support - volatility * 0.25)
    stop = min(stop_candidates)
    target_1 = resistance if resistance is not None and resistance > entry_high else entry_high + 1.5 * volatility
    target_2 = max(target_1 + volatility, entry_high + 3 * volatility)
    if target_1 <= entry_high:
        target_1 = entry_high + 1.5 * volatility
    return stop, target_1, target_2


def _confidence_score(*, trend_score: float, momentum_score: float, volume_score: float,
                      liquidity_score: float, risk_reward: float, market_env: float) -> float:
    """Weighted heuristic evidence ranking; the result is not a probability."""
    rr_score = min(max(risk_reward / 3.0, 0.0), 1.0)
    raw = (.28 * trend_score + .22 * momentum_score + .20 * volume_score
           + .15 * liquidity_score + .10 * rr_score + .05 * market_env)
    return round(max(0.0, min(100.0, 100 * raw)), 1)


def _invalidation_conditions(support: float | None, stop_loss: float) -> list[str]:
    conditions = [f"A daily close below {stop_loss:.6g} weakens the setup."]
    if support is not None:
        conditions.append(f"A sustained daily close below estimated support {support:.6g} invalidates the thesis.")
    conditions.append("The setup is no longer applicable if daily trend or momentum turns bearish.")
    return conditions


class BuyOpportunityScanner:
    """Rank conservative BUY setups from caller-provided daily candles."""

    def __init__(self, market_client: Any | None = None, *, min_confidence: float = 60.0,
                 min_volume_ratio: float = 1.2, min_quote_volume_24h: float | None = None,
                 min_risk_reward: float = 1.3, max_candle_age_days: float | None = None) -> None:
        if not math.isfinite(min_confidence) or not 0 <= min_confidence <= 100:
            raise ValueError("min_confidence must be between 0 and 100")
        if not math.isfinite(min_volume_ratio) or min_volume_ratio < 0:
            raise ValueError("min_volume_ratio must be finite and non-negative")
        if min_quote_volume_24h is not None and (not math.isfinite(min_quote_volume_24h) or min_quote_volume_24h < 0):
            raise ValueError("min_quote_volume_24h must be finite and non-negative")
        if not math.isfinite(min_risk_reward) or min_risk_reward <= 0:
            raise ValueError("min_risk_reward must be finite and positive")
        if max_candle_age_days is not None and (not math.isfinite(max_candle_age_days) or max_candle_age_days <= 0):
            raise ValueError("max_candle_age_days must be finite and positive, or None")
        self.market_client = market_client
        self.min_confidence = min_confidence
        self.min_volume_ratio = min_volume_ratio
        self.min_quote_volume_24h = min_quote_volume_24h
        self.min_risk_reward = min_risk_reward
        self.max_candle_age_days = max_candle_age_days

    def scan(self, symbols: Sequence[str], history_by_symbol: dict[str, dict[str, list[Any]]]) -> list[BuyOpportunity]:
        history_index = {_normalize_symbol(key): value for key, value in history_by_symbol.items() if _normalize_symbol(key)}
        opportunities: list[BuyOpportunity] = []
        for requested_symbol in symbols:
            key = _normalize_symbol(requested_symbol)
            history = history_index.get(key)
            if not key or not history:
                continue
            candles = _valid_candles(history.get("1d", []))
            if len(candles) < 50:
                continue
            latest_time = candles[-1].open_time
            if self.max_candle_age_days is not None:
                if not isinstance(latest_time, datetime):
                    continue
                if latest_time.tzinfo is None:
                    latest_time = latest_time.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - latest_time.astimezone(timezone.utc)).total_seconds() / 86400
                if age_days > self.max_candle_age_days or age_days < -1:
                    continue
            try:
                daily = calculate_indicators(candles)
            except (TypeError, ValueError, ArithmeticError) as exc:
                logger.warning("Skipping %s: daily indicators unavailable (%s)", key, type(exc).__name__)
                continue
            if daily.get("candles", 0) < 50:
                continue
            price, rsi, macd, macd_signal, atr = (
                _safe_float(daily.get(name)) for name in
                ("close", "rsi_14", "macd", "macd_signal", "atr_14")
            )
            trend = daily.get("trend")
            if (price is None or price <= 0 or trend != "bullish" or rsi is None
                    or macd is None or macd_signal is None or atr is None or atr <= 0):
                continue
            support, resistance = _support_resistance(candles)
            if support is None or resistance is None or support <= 0 or resistance <= 0:
                continue
            if rsi < 25 or rsi > 70:
                continue
            volume_ratio = _safe_float(daily.get("volume_vs_20_period"))
            volume_ok = volume_ratio is not None and volume_ratio >= self.min_volume_ratio
            recovery = rsi < 40 and macd >= macd_signal
            if not volume_ok and not recovery:
                continue

            quote_volume = None
            if self.market_client is not None:
                try:
                    ticker = self.market_client.get_ticker(key)
                    quote_volume = _safe_float(getattr(ticker, "quote_volume_24h", None))
                except Exception as exc:
                    logger.warning("Ticker unavailable for %s (%s)", key, type(exc).__name__)
            if self.min_quote_volume_24h is not None and (
                quote_volume is None or quote_volume < self.min_quote_volume_24h
            ):
                continue

            near_support = (price - support) / price <= .04 and price > support
            breakout = resistance < price and macd > macd_signal and volume_ok
            if breakout:
                opp_type = "breakout opportunities"
            elif near_support and rsi < 60:
                opp_type = "support-level rebounds"
            elif rsi >= 40 and macd >= macd_signal:
                opp_type = "trend-following entries"
            else:
                continue

            entry_low, entry_high = _entry_range(
                opportunity_type=opp_type, price=price, support=support, resistance=resistance)
            entry_status = "IMMEDIATE" if entry_low <= price <= entry_high else "WAIT FOR PULLBACK"

            stop, target_1, target_2 = _stop_and_targets(
                price=price, support=support, resistance=resistance, opportunity_type=opp_type,
                atr=atr, entry_low=entry_low, entry_high=entry_high)
            risk_reward = _compute_risk_reward(entry_high, stop, target_1, target_2)
            if not (0 < stop < entry_low <= entry_high < target_1 <= target_2):
                continue
            if risk_reward < self.min_risk_reward:
                continue

            avg_target = (target_1 + target_2) / 2
            upside_pct = round((avg_target - entry_high) / entry_high * 100, 2)
            downside_pct = round((entry_high - stop) / entry_high * 100, 2)
            liquidity_score = (
                min(1.0, quote_volume / self.min_quote_volume_24h / 2)
                if quote_volume is not None and self.min_quote_volume_24h
                else .7
            )
            confidence = _confidence_score(
                trend_score=1.0,
                momentum_score=.8 if 40 <= rsi <= 60 else .6,
                volume_score=1.0 if volume_ok else .5,
                liquidity_score=liquidity_score,
                risk_reward=risk_reward,
                market_env=1.0,
            )
            if confidence < self.min_confidence:
                continue

            reasons = [
                "Daily price/EMA trend is bullish.",
                f"RSI(14) is {rsi:.1f}.",
                f"MACD is {'above' if macd >= macd_signal else 'below'} its signal line.",
            ]
            reasons.append(f"Daily volume is {volume_ratio:.2f}x its 20-candle average." if volume_ratio is not None
                           else "Volume confirmation is unavailable; recovery exception applied.")
            reasons.append(f"Estimated support: {support:.6g}; resistance: {resistance:.6g}.")
            reasons.append("Confidence is a heuristic evidence ranking, not a probability or guarantee.")

            opportunities.append(BuyOpportunity(
                symbol=key, name=_symbol_name(key), pair=key, price=price,
                entry_low=entry_low, entry_high=entry_high, trend=trend,
                opportunity_type=opp_type, reasons=reasons, rsi_14=rsi, macd=macd,
                macd_signal=macd_signal, macd_histogram=macd-macd_signal,
                volume_confirmation=volume_ok, support=support, resistance=resistance,
                stop_loss=stop, target_1=target_1, target_2=target_2,
                potential_upside_pct=upside_pct, potential_downside_pct=downside_pct,
                risk_reward=risk_reward, confidence_score=confidence,
                recommended_holding_timeframe="1-6 weeks",
                invalidation_conditions=_invalidation_conditions(support, stop),
                market_condition="constructive", entry_status=entry_status,
            ))
        return sorted(opportunities, key=lambda item: (-item.confidence_score, -(item.risk_reward or 0), item.symbol))


def detect_best_buy_opportunity(market_client: Any | None, symbols: Sequence[str],
                                history_by_symbol: dict[str, dict[str, list[Any]]]) -> list[BuyOpportunity]:
    """Return eligible heuristic BUY setups ranked by evidence score."""
    return BuyOpportunityScanner(market_client=market_client).scan(symbols, history_by_symbol)


def recommend_best_buy(market_client: Any | None, symbols: Sequence[str],
                       history_by_symbol: dict[str, dict[str, list[Any]]]) -> tuple[str, str | None, list[BuyOpportunity]]:
    """Return BUY when a setup passes filters, otherwise WAIT; never execute trades."""
    ranked = detect_best_buy_opportunity(market_client, symbols, history_by_symbol)
    return ("BUY", ranked[0].symbol, ranked) if ranked else ("WAIT", None, [])


__all__ = ["BuyOpportunity", "BuyOpportunityScanner", "detect_best_buy_opportunity", "recommend_best_buy"]

if __name__ == "__main__":
    print("Buy opportunity detection module ready.")
