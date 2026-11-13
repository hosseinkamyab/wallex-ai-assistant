"""Deterministic, read-only cryptocurrency market analysis.

Indicator math is independent of any language model. All outputs are derived
only from the supplied OHLCV candles; unavailable inputs remain None.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .market_client import Candle, MarketClient

TIMEFRAMES: dict[str, str] = {"15m": "15", "1h": "60", "4h": "240", "1d": "D", "1w": "W"}
SIGNALS = ("STRONG BUY", "BUY", "WAIT FOR ENTRY", "HOLD", "TAKE PROFIT", "SELL", "STRONG SELL", "AVOID")


@dataclass(frozen=True)
class ScoringWeights:
    """Weights for independent evidence groups (not individual indicators)."""
    trend: float = 0.22
    momentum: float = 0.18
    volume: float = 0.10
    volatility: float = 0.10
    timeframe_agreement: float = 0.18
    risk_reward: float = 0.12
    market: float = 0.10

    def __post_init__(self) -> None:
        values = [getattr(self, name) for name in self.__dataclass_fields__]
        if any(value < 0 for value in values) or sum(values) <= 0:
            raise ValueError("Scoring weights must be non-negative with a positive total")

    def as_dict(self) -> dict[str, float]:
        total = sum(getattr(self, name) for name in self.__dataclass_fields__)
        return {name: getattr(self, name) / total for name in self.__dataclass_fields__}


@dataclass
class MarketContext:
    observed_at: str
    btc_direction: str = "unknown"
    breadth: float | None = None
    volatility: str = "unknown"
    risk_condition: str = "unknown"
    symbols_analyzed: int = 0


@dataclass
class AnalysisResult:
    symbol: str
    signal: str | None
    score: float | None
    data_as_of: str | None
    timeframe_indicators: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "signal": self.signal, "score": self.score,
                "data_as_of": self.data_as_of, "timeframe_indicators": self.timeframe_indicators,
                "evidence": self.evidence, "explanation": self.explanation, "warnings": self.warnings}


def _series(values: Sequence[float]) -> pd.Series:
    return pd.Series(values, dtype="float64")


def calculate_indicators(candles: Sequence[Candle], *, support_window: int = 50) -> dict[str, Any]:
    """Calculate reproducible indicators for ascending OHLCV candles.

    Wilder smoothing is used for RSI, ATR, and ADX. Rolling standard deviation
    uses population ddof=0 for Bollinger Bands. No forward filling is performed.
    """
    ordered = sorted(candles, key=lambda candle: candle.open_time)
    if not ordered:
        return {"candles": 0, "data_as_of": None}
    close, high, low = (_series([float(getattr(c, name)) for c in ordered]) for name in ("close", "high", "low"))
    volume_values = [float(c.volume) if c.volume is not None else np.nan for c in ordered]
    volume = _series(volume_values)
    prev = close.shift(1)

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(loss.ne(0), 100).where(~((gain == 0) & (loss == 0)), 50)

    ema = {period: close.ewm(span=period, adjust=False, min_periods=period).mean() for period in (9, 21, 50, 200)}
    sma = {period: close.rolling(period, min_periods=period).mean() for period in (20, 50, 200)}
    macd_line = close.ewm(span=12, adjust=False, min_periods=26).mean() - close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd_signal = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    up_move, down_move = high.diff(), -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    bb_mid = close.rolling(20, min_periods=20).mean()
    bb_std = close.rolling(20, min_periods=20).std(ddof=0)
    vol_avg = volume.rolling(20, min_periods=20).mean()
    last_volume = volume.iloc[-1]
    volume_change = (last_volume / volume.iloc[-2] - 1) * 100 if len(volume) > 1 and pd.notna(last_volume) and pd.notna(volume.iloc[-2]) and volume.iloc[-2] != 0 else np.nan
    momentum = (close.iloc[-1] / close.iloc[-11] - 1) * 100 if len(close) >= 11 and close.iloc[-11] else np.nan
    pivot_window = min(support_window, len(close))
    support = low.iloc[-pivot_window:].min() if pivot_window else np.nan
    resistance = high.iloc[-pivot_window:].max() if pivot_window else np.nan
    last = len(close) - 1
    last_close = close.iloc[last]
    trend = "bullish" if pd.notna(ema[21].iloc[last]) and pd.notna(ema[50].iloc[last]) and last_close > ema[21].iloc[last] > ema[50].iloc[last] else "bearish" if pd.notna(ema[21].iloc[last]) and pd.notna(ema[50].iloc[last]) and last_close < ema[21].iloc[last] < ema[50].iloc[last] else "neutral"
    adx_value = adx.iloc[last]
    values: dict[str, Any] = {
        "candles": len(ordered), "data_as_of": ordered[-1].open_time.astimezone(timezone.utc).isoformat(),
        "close": last_close, "rsi_14": rsi.iloc[last], "macd": macd_line.iloc[last], "macd_signal": macd_signal.iloc[last],
        "ema_9": ema[9].iloc[last], "ema_21": ema[21].iloc[last], "ema_50": ema[50].iloc[last], "ema_200": ema[200].iloc[last],
        "sma_20": sma[20].iloc[last], "sma_50": sma[50].iloc[last], "sma_200": sma[200].iloc[last],
        "bollinger_lower": (bb_mid - 2 * bb_std).iloc[last], "bollinger_middle": bb_mid.iloc[last], "bollinger_upper": (bb_mid + 2 * bb_std).iloc[last],
        "atr_14": atr.iloc[last], "atr_percent": atr.iloc[last] / last_close * 100 if last_close else np.nan,
        "adx_14": adx_value, "plus_di": plus_di.iloc[last], "minus_di": minus_di.iloc[last],
        "volume": last_volume, "volume_change_percent": volume_change,
        "volume_vs_20_period": last_volume / vol_avg.iloc[last] if pd.notna(last_volume) and pd.notna(vol_avg.iloc[last]) and vol_avg.iloc[last] else np.nan,
        "momentum_10_period_percent": momentum, "support": support, "resistance": resistance, "trend": trend,
        "trend_strength": "strong" if pd.notna(adx_value) and adx_value >= 25 else "weak" if pd.notna(adx_value) else "unknown",
        "breakout": bool(last_close > resistance) if pd.notna(resistance) else False,
        "breakdown": bool(last_close < support) if pd.notna(support) else False,
    }
    return {key: _clean(value) for key, value in values.items()}


def _clean(value: Any) -> Any:
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    return value


def analyze_market(candles_by_symbol: Mapping[str, Mapping[str, Sequence[Candle]]], *, btc_symbol: str = "BTC TMN", weights: ScoringWeights | None = None, minimum_candles: int = 50) -> tuple[MarketContext, list[AnalysisResult]]:
    """Analyze per-symbol candles for all five timeframes and score evidence."""
    weights = weights or ScoringWeights()
    summaries: dict[str, dict[str, dict[str, Any]]] = {}
    for symbol, frames in candles_by_symbol.items():
        summaries[symbol] = {tf: calculate_indicators(frames.get(tf, ())) for tf in TIMEFRAMES}
    btc_key = next((key for key in summaries if key.upper().replace("/", "").replace("-", "") == btc_symbol.upper().replace("/", "").replace("-", "")), None)
    btc_daily = summaries.get(btc_key, {}).get("1d", {}) if btc_key else {}
    btc_direction = btc_daily.get("trend", "unknown") if btc_daily.get("candles", 0) >= minimum_candles else "unknown"
    eligible = [frames["1d"] for frames in summaries.values() if frames["1d"].get("candles", 0) >= minimum_candles and frames["1d"].get("trend") in ("bullish", "bearish")]
    breadth = sum(x["trend"] == "bullish" for x in eligible) / len(eligible) if eligible else None
    daily_atrs = [frames["1d"].get("atr_percent") for frames in summaries.values() if frames["1d"].get("atr_percent") is not None]
    volatility = "high" if daily_atrs and float(np.median(daily_atrs)) >= 5 else "normal" if daily_atrs else "unknown"
    risk = "elevated" if volatility == "high" or btc_direction == "bearish" or (breadth is not None and breadth < .3) else "constructive" if btc_direction == "bullish" and breadth is not None and breadth > .6 else "mixed" if breadth is not None else "unknown"
    context = MarketContext(datetime.now(timezone.utc).isoformat(), btc_direction, breadth, volatility, risk, len(summaries))
    results = [_score_symbol(symbol, frames, context, weights, minimum_candles) for symbol, frames in summaries.items()]
    return context, results


def _score_symbol(symbol: str, frames: dict[str, dict[str, Any]], market: MarketContext, weights: ScoringWeights, minimum: int) -> AnalysisResult:
    warnings: list[str] = []
    usable = {tf: data for tf, data in frames.items() if data.get("candles", 0) >= minimum}
    as_of = max((x["data_as_of"] for x in frames.values() if x.get("data_as_of")), default=None)
    if len(usable) < 2 or "1d" not in usable:
        missing = [tf for tf in TIMEFRAMES if frames[tf].get("candles", 0) < minimum]
        return AnalysisResult(symbol, None, None, as_of, frames, {}, "Insufficient historical OHLCV data for a signal; no recommendation generated.", [f"At least {minimum} candles on the daily timeframe and one other timeframe are required.", f"Insufficient timeframes: {', '.join(missing)}"])
    daily = usable["1d"]
    # Each category is a bounded composite; RSI/MACD/price momentum are grouped,
    # as are moving averages, so correlated indicators are not counted as votes.
    trend_value = _direction_value(daily.get("trend"))
    if daily.get("adx_14") is not None:
        trend_value *= min(1.0, max(.35, daily["adx_14"] / 35))
    momentum_parts = []
    if daily.get("rsi_14") is not None:
        momentum_parts.append(float(np.clip((daily["rsi_14"] - 50) / 25, -1, 1)))
    if daily.get("macd") is not None and daily.get("macd_signal") is not None:
        momentum_parts.append(float(np.sign(daily["macd"] - daily["macd_signal"])))
    if daily.get("momentum_10_period_percent") is not None:
        momentum_parts.append(float(np.tanh(daily["momentum_10_period_percent"] / 5)))
    momentum_value = float(np.mean(momentum_parts)) if momentum_parts else None
    volume_ratio = daily.get("volume_vs_20_period")
    volume_change = daily.get("volume_change_percent")
    volume_value = (float(np.sign(daily.get("momentum_10_period_percent") or 0)) if volume_ratio is not None and volume_ratio >= 1.2 else 0.0) if volume_ratio is not None else None
    atr_pct = daily.get("atr_percent")
    volatility_value = float(np.clip(1 - (atr_pct or 0) / 10, -1, 1)) if atr_pct is not None else None
    directions = [_direction_value(data.get("trend")) for tf, data in usable.items() if tf in ("1h", "4h", "1d", "1w") and data.get("trend") != "neutral"]
    agreement = float(np.mean(directions)) if directions else None
    rr = None
    close, support, resistance = (daily.get(k) for k in ("close", "support", "resistance"))
    if close and support is not None and resistance is not None and resistance > close and close > support:
        upside, downside = (resistance - close) / close, (close - support) / close
        rr = float(np.clip((upside / downside) / 3 - 1, -1, 1)) if downside > 0 else 1.0
    elif daily.get("trend") == "bullish" and support and close and support < close:
        rr = 0.0
    market_value = _direction_value(market.btc_direction) if market.btc_direction != "unknown" else None
    if market.breadth is not None:
        breadth_value = (market.breadth - .5) * 2
        market_value = breadth_value if market_value is None else .5 * market_value + .5 * breadth_value
    components = {"trend": trend_value, "momentum": momentum_value, "volume": volume_value,
                  "volatility": volatility_value, "timeframe_agreement": agreement,
                  "risk_reward": rr, "market": market_value}
    weight_map = weights.as_dict()
    active = {name: value for name, value in components.items() if value is not None and weight_map[name] > 0}
    normalized_weight = sum(weight_map[name] for name in active)
    score = 50 + 50 * sum(weight_map[name] * value for name, value in active.items()) / normalized_weight if active else None
    score = round(float(np.clip(score, 0, 100)), 1) if score is not None else None
    # Countertrend short timeframe is an explicit wait, even if daily is bullish.
    short = usable.get("1h", {}).get("trend")
    if daily["trend"] == "bullish" and short == "bearish":
        signal = "WAIT FOR ENTRY"
    elif score is None:
        signal = None
    elif score >= 78 and daily["trend"] == "bullish":
        signal = "STRONG BUY"
    elif score >= 62 and daily["trend"] == "bullish":
        signal = "BUY"
    elif score <= 22 and daily["trend"] == "bearish":
        signal = "STRONG SELL"
    elif score <= 38 and daily["trend"] == "bearish":
        signal = "SELL"
    elif daily.get("rsi_14") is not None and daily["rsi_14"] >= 75 and daily["trend"] == "bullish":
        signal = "TAKE PROFIT"
    elif score <= 45:
        signal = "AVOID"
    else:
        signal = "HOLD"
    if market.risk_condition == "elevated" and signal in ("STRONG BUY", "BUY"):
        signal = "HOLD"
        warnings.append("Market-wide risk is elevated; bullish asset evidence was downgraded to HOLD.")
    explanation = _explain(symbol, signal, score, daily, usable, components, market)
    if volume_change is not None and volume_ratio is not None and volume_ratio >= 2:
        warnings.append("Unusual volume: current daily volume is at least 2x its 20-period average.")
    if daily.get("breakout"):
        warnings.append("Price is above the rolling resistance estimate (potential breakout; confirmation is not guaranteed).")
    if daily.get("breakdown"):
        warnings.append("Price is below the rolling support estimate (potential breakdown).")
    return AnalysisResult(symbol, signal, score, as_of, frames, {"components": components, "weights": weight_map, "market_risk": market.risk_condition}, explanation, warnings)


def _direction_value(direction: str | None) -> float:
    return 1.0 if direction == "bullish" else -1.0 if direction == "bearish" else 0.0


def _explain(symbol: str, signal: str | None, score: float | None, daily: Mapping[str, Any], usable: Mapping[str, Any], components: Mapping[str, Any], market: MarketContext) -> str:
    if signal is None:
        return "Insufficient evidence; no signal generated."
    positives = [name.replace("_", " ") for name, value in components.items() if value is not None and value >= .25]
    negatives = [name.replace("_", " ") for name, value in components.items() if value is not None and value <= -.25]
    timeframe = ", ".join(f"{tf} {data['trend']}" for tf, data in usable.items() if tf in ("1h", "4h", "1d", "1w"))
    reasons = []
    if positives: reasons.append("supporting evidence: " + ", ".join(positives))
    if negatives: reasons.append("counter-evidence: " + ", ".join(negatives))
    if daily.get("rsi_14") is not None: reasons.append(f"daily RSI(14) {daily['rsi_14']:.1f}")
    if daily.get("adx_14") is not None: reasons.append(f"daily ADX(14) {daily['adx_14']:.1f}")
    if timeframe: reasons.append("timeframes: " + timeframe)
    if market.btc_direction != "unknown": reasons.append(f"BTC daily direction {market.btc_direction}")
    return f"{symbol}: {signal} (evidence score {score:.1f}/100). " + "; ".join(reasons) + ". Score combines normalized, weighted evidence groups; it is not a probability or return forecast."


def fetch_market_history(client: MarketClient, symbols: Sequence[str], *, bars: int = 300, now: datetime | None = None) -> dict[str, dict[str, list[Candle]]]:
    """Fetch up to ``bars`` recent candles per symbol/timeframe from Wallex."""
    if bars < 1:
        raise ValueError("bars must be positive")
    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    result: dict[str, dict[str, list[Candle]]] = {}
    seconds = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}
    for symbol in symbols:
        result[symbol] = {}
        for timeframe, resolution in TIMEFRAMES.items():
            start = end.timestamp() - bars * seconds[timeframe]
            result[symbol][timeframe] = client.get_history(symbol, resolution, int(start), int(end.timestamp()))
    return result


def analyze_with_client(client: MarketClient, symbols: Sequence[str], *, bars: int = 300, weights: ScoringWeights | None = None, now: datetime | None = None) -> tuple[MarketContext, list[AnalysisResult]]:
    """Fetch real public OHLCV, tolerate per-market/timeframe failures, analyze."""
    history: dict[str, dict[str, list[Candle]]] = {}
    for symbol in symbols:
        history[symbol] = {}
        for timeframe, resolution in TIMEFRAMES.items():
            end = now or datetime.now(timezone.utc)
            if end.tzinfo is None:
                raise ValueError("now must be timezone-aware")
            start = int(end.timestamp() - bars * {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}[timeframe])
            try:
                history[symbol][timeframe] = client.get_history(symbol, resolution, start, int(end.timestamp()))
            except Exception as exc:  # retain data that succeeded in other timeframes
                history[symbol][timeframe] = []
                # Record the API failure on the result below without leaking credentials.
                history[symbol].setdefault("_errors", []).append(f"{timeframe}: {type(exc).__name__}: {exc}")
    context, results = analyze_market(history, weights=weights)
    for result in results:
        result.warnings.extend(history[result.symbol].get("_errors", []))
    return context, results


__all__ = ["AnalysisResult", "MarketContext", "ScoringWeights", "TIMEFRAMES", "analyze_market", "analyze_with_client", "calculate_indicators", "fetch_market_history"]
