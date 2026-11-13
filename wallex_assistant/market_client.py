from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .config import Settings, get_settings
from .errors import WallexAPIError, WallexResponseError
from .http import WallexHttpClient

logger = logging.getLogger(__name__)


def _pick(data: dict[str, Any], *keys: str) -> Any:
    """Return the first present non-None value from a dict."""
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _to_decimal(value: Any, field: str, context: str) -> Decimal:
    """Convert a price/quantity-like value to Decimal or raise a clear error."""
    if value is None or value == "":
        raise WallexResponseError(
            f"Missing {field!r} for {context!r}",
            endpoint="market-data",
        )
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise WallexResponseError(
            f"Field {field!r} for {context!r} is not numeric: {value!r}",
            endpoint="market-data",
        ) from exc


def _optional_decimal(value: Any) -> Decimal | None:
    """Parse a value that can be missing or malformed."""
    if value in (None, "", "-"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


@dataclass
class Candle:
    """One OHLCV candle."""

    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None

    @classmethod
    def from_udf_row(cls, ts: Any, o: Any, h: Any, l: Any, c: Any, v: Any) -> "Candle":
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return cls(
            open_time=dt,
            open=_to_decimal(o, "open", "candle"),
            high=_to_decimal(h, "high", "candle"),
            low=_to_decimal(l, "low", "candle"),
            close=_to_decimal(c, "close", "candle"),
            volume=_optional_decimal(v),
        )


@dataclass
class MarketStat:
    symbol: str
    base_asset: str | None = None
    quote_asset: str | None = None
    last_price: Decimal | None = None
    price_change_percent_24h: Decimal | None = None
    high_24h: Decimal | None = None
    low_24h: Decimal | None = None
    volume_24h: Decimal | None = None
    quote_volume_24h: Decimal | None = None
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None

    @classmethod
    def from_api(cls, symbol: str, payload: dict[str, Any]) -> "MarketStat":
        stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else payload
        best_bid = _optional_decimal(_pick(payload, "best_bid", "bestBid"))
        best_ask = _optional_decimal(_pick(payload, "best_ask", "bestAsk"))
        last_price = _optional_decimal(
            _pick(stats, "lastPrice", "last_price", "price", "last")
        )
        pct = _optional_decimal(
            _pick(stats, "priceChangePercent", "price_change_percent", "change_24h", "change24h")
        )
        high = _optional_decimal(_pick(stats, "highPrice", "high_price", "high_24h"))
        low = _optional_decimal(_pick(stats, "lowPrice", "low_price", "low_24h"))
        volume = _optional_decimal(_pick(stats, "volume", "volume_24h", "quoteVolume"))
        quote_volume = _optional_decimal(_pick(stats, "quoteVolume", "quote_volume_24h"))
        return cls(
            symbol=str(symbol).upper(),
            base_asset=_pick(payload, "baseAsset", "base_asset"),
            quote_asset=_pick(payload, "quoteAsset", "quote_asset"),
            last_price=last_price,
            price_change_percent_24h=pct,
            high_24h=high,
            low_24h=low,
            volume_24h=volume,
            quote_volume_24h=quote_volume,
            best_bid=best_bid,
            best_ask=best_ask,
        )

    def as_dict(self) -> dict[str, str | None]:
        return {
            "symbol": self.symbol,
            "last_price": str(self.last_price) if self.last_price is not None else None,
            "price_change_percent_24h": (
                str(self.price_change_percent_24h)
                if self.price_change_percent_24h is not None
                else None
            ),
            "volume_24h": str(self.volume_24h) if self.volume_24h is not None else None,
        }


class MarketClient:
    """Read-only public market client for Wallex."""

    def __init__(self, http: Any):
        self._http = http

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "MarketClient":
        settings = settings or get_settings()
        http = WallexHttpClient(settings.wallex_base_url, api_key=None, timeout=settings.request_timeout, max_retries=settings.max_retries)
        return cls(http)

    def close(self) -> None:
        close = getattr(self._http, "close", None)
        if callable(close):
            close()

    def get_markets(self) -> dict[str, dict[str, Any]]:
        """Fetch active markets from the official Wallex endpoint."""
        payload = self._http.get("/hector/web/v1/markets")
        if not isinstance(payload, dict):
            raise WallexResponseError("Wallex market response was not a JSON object", endpoint="/hector/web/v1/markets")

        result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
        items: Any = None
        if isinstance(result, dict):
            items = result.get("markets") if isinstance(result.get("markets"), list) else result.get("symbols")
        if items is None and isinstance(payload, dict):
            items = payload.get("markets")

        if not isinstance(items, dict) and not isinstance(items, list):
            raise WallexResponseError("Wallex market data is missing the expected 'markets' list", endpoint="/hector/web/v1/markets")

        mapping: dict[str, dict[str, Any]] = {}
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                symbol = str(_pick(item, "symbol", "market") or "").upper()
                if not symbol:
                    continue
                mapping[symbol] = item
        elif isinstance(items, dict):
            for symbol, item in items.items():
                if isinstance(item, dict):
                    mapping[str(symbol).upper()] = item
                else:
                    mapping[str(symbol).upper()] = {"symbol": symbol, "value": item}
        return mapping

    def list_symbols(self) -> list[str]:
        return sorted(self.get_markets())

    def get_market_stats(self) -> list[MarketStat]:
        stats = []
        for symbol, payload in self.get_markets().items():
            if not isinstance(payload, dict):
                continue
            stats.append(MarketStat.from_api(symbol, payload))
        return stats

    def get_ticker(self, symbol: str) -> MarketStat:
        market_map = self.get_markets()
        normalized = symbol.upper()
        for key, value in market_map.items():
            if key.upper() == normalized:
                return MarketStat.from_api(key, value)
        raise WallexResponseError(f"Unknown market symbol {symbol!r}", endpoint="/hector/web/v1/markets")

    def get_orderbook(self, symbol: str, limit: int = 20) -> dict[str, list[list[str]]]:
        payload = self._http.get("/v1/depth", params={"symbol": symbol})
        result = payload.get("result") if isinstance(payload, dict) else payload
        if not isinstance(result, dict):
            raise WallexResponseError("Wallex depth response did not contain a result object", endpoint="/v1/depth")
        raw_bids = result.get("bids") if isinstance(result.get("bids"), list) else result.get("bid")
        raw_asks = result.get("asks") if isinstance(result.get("asks"), list) else result.get("ask")
        if not isinstance(raw_bids, list) or not isinstance(raw_asks, list):
            raise WallexResponseError("Wallex depth response had an unexpected shape", endpoint="/v1/depth")
        bids = [list(map(str, row)) for row in raw_bids[:limit]]
        asks = [list(map(str, row)) for row in raw_asks[:limit]]
        return {"bids": bids, "asks": asks}

    def get_trades(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        payload = self._http.get("/v1/trades", params={"symbol": symbol})
        result = payload.get("result") if isinstance(payload, dict) else payload
        trades = result.get("trades") if isinstance(result, dict) else None
        if not isinstance(trades, list):
            raise WallexResponseError("Wallex trades response had an unexpected shape", endpoint="/v1/trades")
        return trades[:limit]

    @staticmethod
    def _candles_from_udf(payload: dict[str, Any], symbol: str) -> list[Candle]:
        if not isinstance(payload, dict):
            raise WallexResponseError(f"Candles payload was not a dict for {symbol!r}", endpoint="/v1/udf/history")
        if payload.get("s") == "no_data":
            return []
        if payload.get("s") not in {"ok", None, "": "ok"} and payload.get("s") != "ok":
            raise WallexResponseError(f"Candles API returned status {payload.get('s')!r} for {symbol!r}", endpoint="/v1/udf/history")

        times = payload.get("t")
        opens = payload.get("o")
        highs = payload.get("h")
        lows = payload.get("l")
        closes = payload.get("c")
        vols = payload.get("v", [])
        if not all(isinstance(v, list) for v in (times, opens, highs, lows, closes)):
            raise WallexResponseError(f"Candles payload for {symbol!r} was missing arrays", endpoint="/v1/udf/history")
        length = min(len(times), len(opens), len(highs), len(lows), len(closes))
        candles: list[Candle] = []
        for idx in range(length):
            candles.append(
                Candle.from_udf_row(
                    times[idx],
                    opens[idx],
                    highs[idx],
                    lows[idx],
                    closes[idx],
                    vols[idx] if idx < len(vols) else None,
                )
            )
        return candles


__all__ = [
    "Candle",
    "MarketClient",
    "MarketStat",
    "_optional_decimal",
    "_pick",
    "_to_decimal",
]
