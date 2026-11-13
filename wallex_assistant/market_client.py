"""Read-only client for public Wallex market data and OHLCV history."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .config import Settings, get_settings
from .errors import WallexResponseError
from .http import WallexHttpClient

logger = logging.getLogger(__name__)


def _pick(data: dict[str, Any], *keys: str) -> Any:
    """Return the first present, non-None value among keys."""
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _to_decimal(value: Any, field: str, context: str) -> Decimal:
    """Convert an API value to a finite Decimal or raise a clear error."""
    if value is None or value == "":
        raise WallexResponseError(f"Missing numeric field {field!r} in {context}")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise WallexResponseError(
            f"Field {field!r} in {context} is not a number: {value!r}"
        ) from exc
    if not result.is_finite():
        raise WallexResponseError(
            f"Field {field!r} in {context} is not finite: {value!r}"
        )
    return result


def _optional_decimal(value: Any) -> Decimal | None:
    """Convert optional API values to finite Decimal, otherwise None."""
    if value is None or value in ("", "-"):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


@dataclass(frozen=True)
class Candle:
    """One OHLCV candle. All times are UTC."""

    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None


@dataclass(frozen=True)
class MarketStat:
    """A snapshot for one trading pair, such as BTCTMN."""

    symbol: str
    last_price: Decimal | None = None
    price_change_24h: Decimal | None = None
    price_change_percent_24h: Decimal | None = None
    high_24h: Decimal | None = None
    low_24h: Decimal | None = None
    volume_24h: Decimal | None = None
    quote_volume_24h: Decimal | None = None
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None

    @classmethod
    def from_api(cls, symbol: str, raw: dict[str, Any]) -> "MarketStat":
        stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else raw
        return cls(
            symbol=symbol,
            last_price=_optional_decimal(_pick(stats, "lastPrice", "last_price", "price", "last")),
            price_change_24h=_optional_decimal(_pick(stats, "priceChange", "price_change", "change")),
            price_change_percent_24h=_optional_decimal(
                _pick(stats, "priceChangePercent", "price_change_percent", "change_percent", "change_24h", "change24h")
            ),
            high_24h=_optional_decimal(_pick(stats, "highPrice", "high_price", "high_24h", "high")),
            low_24h=_optional_decimal(_pick(stats, "lowPrice", "low_price", "low_24h", "low")),
            volume_24h=_optional_decimal(_pick(stats, "volume", "base_volume", "volume_24h")),
            quote_volume_24h=_optional_decimal(_pick(stats, "quoteVolume", "quote_volume", "volume_tmn")),
            best_bid=_optional_decimal(_pick(raw, "best_bid", "bestBid", "bid")),
            best_ask=_optional_decimal(_pick(raw, "best_ask", "bestAsk", "ask")),
        )

    def as_dict(self) -> dict[str, str | None]:
        """Return a JSON-friendly representation."""
        return {
            "symbol": self.symbol,
            "last_price": _string_or_none(self.last_price),
            "price_change_24h": _string_or_none(self.price_change_24h),
            "price_change_percent_24h": _string_or_none(self.price_change_percent_24h),
            "high_24h": _string_or_none(self.high_24h),
            "low_24h": _string_or_none(self.low_24h),
            "volume_24h": _string_or_none(self.volume_24h),
            "quote_volume_24h": _string_or_none(self.quote_volume_24h),
            "best_bid": _string_or_none(self.best_bid),
            "best_ask": _string_or_none(self.best_ask),
        }


def _string_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


class MarketClient:
    """Read-only access to Wallex public market data."""

    def __init__(self, http: Any) -> None:
        self._http = http

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "MarketClient":
        """Build a public-data client; public requests never use an API key."""
        settings = settings or get_settings()
        http = WallexHttpClient(
            base_url=settings.wallex_base_url,
            api_key=None,
            timeout=settings.request_timeout,
            max_retries=settings.max_retries,
        )
        return cls(http)

    def get_markets(self) -> dict[str, dict[str, Any]]:
        """Fetch markets from Wallex's current public markets endpoint."""
        endpoint = "/hector/web/v1/markets"
        payload = self._http.get(endpoint)
        if not isinstance(payload, dict):
            raise WallexResponseError("Wallex market response was not a JSON object", endpoint=endpoint)

        result = payload.get("result")
        container = result if isinstance(result, dict) else payload
        items = container.get("markets") or container.get("symbols")
        if items is None:
            # Some API payloads wrap the market mapping directly in result.
            items = container if container is not payload else None
        if isinstance(items, dict):
            markets = {
                str(symbol).upper(): value if isinstance(value, dict) else {"symbol": symbol, "value": value}
                for symbol, value in items.items()
            }
        elif isinstance(items, list):
            markets = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                symbol = _pick(item, "symbol", "market")
                if symbol:
                    markets[str(symbol).upper()] = item
            if items and not markets:
                raise WallexResponseError("Wallex markets list contained no valid market entries", endpoint=endpoint)
        else:
            raise WallexResponseError("Wallex market response had an unexpected shape", endpoint=endpoint)

        logger.debug("Fetched %d markets", len(markets))
        return markets

    def list_symbols(self) -> list[str]:
        return sorted(self.get_markets())

    def get_market_stats(self) -> list[MarketStat]:
        """Parse public market snapshots."""
        return [MarketStat.from_api(symbol, raw) for symbol, raw in self.get_markets().items()]

    def get_ticker(self, symbol: str) -> MarketStat:
        wanted = symbol.upper()
        for market_symbol, raw in self.get_markets().items():
            if market_symbol.upper() == wanted:
                return MarketStat.from_api(market_symbol, raw)
        raise WallexResponseError(f"Symbol {symbol!r} was not found in market data")

    def get_orderbook(self, symbol: str, *, limit: int = 20) -> dict[str, Any]:
        payload = self._http.get("/v1/depth", params={"symbol": symbol.upper()})
        book = payload.get("depth") or payload.get("result") or payload if isinstance(payload, dict) else None
        if not isinstance(book, dict) or not isinstance(book.get("bids"), list) or not isinstance(book.get("asks"), list):
            raise WallexResponseError("/v1/depth did not contain bids and asks")
        return {**book, "bids": book["bids"][:limit], "asks": book["asks"][:limit]}

    def get_trades(self, symbol: str, *, limit: int = 50) -> list[dict[str, Any]]:
        payload = self._http.get("/v1/trades", params={"symbol": symbol.upper()})
        trades = payload.get("trades") or payload.get("lastTrade") or payload.get("result") or payload if isinstance(payload, dict) else payload
        if isinstance(trades, dict):
            trades = trades.get("trades", [])
        if not isinstance(trades, list):
            raise WallexResponseError("Expected /v1/trades to return a list")
        return trades[:limit]

    def get_history(
        self, symbol: str, resolution: str, start: int, end: int
    ) -> list[Candle]:
        """Fetch OHLCV candles using Unix-second bounds and UDF resolution."""
        if start >= end:
            raise ValueError("start must be earlier than end")
        payload = self._http.get(
            "/v1/udf/history",
            params={"symbol": symbol.upper(), "resolution": str(resolution), "from": start, "to": end},
        )
        return sorted(self._candles_from_udf(payload, symbol), key=lambda candle: candle.open_time)

    def get_ohlc(
        self,
        symbol: str,
        *,
        resolution: int = 60,
        days: int = 7,
        end: datetime | None = None,
    ) -> list[Candle]:
        """Compatibility helper to fetch recent candles by day count."""
        end_time = end or datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=days)
        return self.get_history(symbol, str(resolution), int(start_time.timestamp()), int(end_time.timestamp()))

    @staticmethod
    def _candles_from_udf(payload: dict[str, Any], symbol: str) -> list[Candle]:
        """Convert the UDF parallel-array response to candle objects."""
        if not isinstance(payload, dict):
            raise WallexResponseError(f"UDF history response for {symbol!r} was not an object")
        status = payload.get("s")
        if status == "no_data":
            return []
        if status not in (None, "", "ok"):
            raise WallexResponseError(f"UDF history returned status {status!r} for {symbol}")

        times, opens, highs, lows, closes = (payload.get(key) for key in ("t", "o", "h", "l", "c"))
        volumes = payload.get("v", [])
        if not all(isinstance(values, list) for values in (times, opens, highs, lows, closes)):
            raise WallexResponseError("UDF history fields t/o/h/l/c must all be lists")
        if not isinstance(volumes, list):
            raise WallexResponseError("UDF history volume field v must be a list")

        count = min(map(len, (times, opens, highs, lows, closes)))
        candles = []
        for index in range(count):
            try:
                candles.append(Candle(
                    open_time=datetime.fromtimestamp(int(times[index]), tz=timezone.utc),
                    open=_to_decimal(opens[index], "open", symbol),
                    high=_to_decimal(highs[index], "high", symbol),
                    low=_to_decimal(lows[index], "low", symbol),
                    close=_to_decimal(closes[index], "close", symbol),
                    volume=_optional_decimal(volumes[index] if index < len(volumes) else None),
                ))
            except (ValueError, TypeError, OSError, OverflowError, InvalidOperation) as exc:
                raise WallexResponseError(f"Malformed candle {index} for {symbol}: {exc}") from exc
        return candles

    def close(self) -> None:
        close = getattr(self._http, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "MarketClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


__all__ = ["Candle", "MarketClient", "MarketStat", "_optional_decimal", "_pick", "_to_decimal"]
