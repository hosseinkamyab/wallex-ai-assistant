"""Read-only client for Wallex *public* market data.

None of these calls need an API key: prices are public information. That makes
this the safest possible place to start -- we prove the whole stack works
(config -> HTTP -> parsing -> logging) before a credential is ever involved.

Endpoints used (all GET, all read-only):

    GET /v1/markets                  list of tradeable symbols
    GET /v1/market-status            summary for every symbol (price, volume)
    GET /v1/depth?symbol=BTCTMN      order book
    GET /v1/trades?symbol=BTCTMN     recent trades
    GET /v1/udf/history?...          OHLC candle history

A note on the shape of this file: because API field names can drift, parsing
is deliberately *tolerant* -- it accepts several plausible key names and
raises a clear `WallexResponseError` naming the field it could not find. If the
API ever changes, the error tells you exactly what to fix, and

    python -m wallex_assistant.market_client --probe

prints the raw JSON so you can see the real names.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .config import ConfigError, Settings, get_settings
from .errors import WallexError, WallexResponseError
from .http import WallexHttpClient
from .logging_setup import setup_logging
from .readonly import ReadOnlyClient

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helpers for tolerant field access
# --------------------------------------------------------------------------- #
def _pick(data: dict[str, Any], *keys: str) -> Any:
    """Return the first present, non-None value among `keys`.

    Lets one function cope with `lastPrice`, `last_price` and `price` without
    three branches. Returns None when none of them exist.
    """
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _to_decimal(value: Any, field: str, context: str) -> Decimal:
    """Convert an API value to Decimal, with an error that names the field.

    We use Decimal rather than float for money: floats cannot represent 0.1
    exactly, and those tiny errors compound across thousands of balance rows.
    """
    if value is None:
        raise WallexResponseError(
            f"Missing numeric field {field!r} in {context}"
        )
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise WallexResponseError(
            f"Field {field!r} in {context} is not a number: {value!r}"
        ) from exc


def _optional_decimal(value: Any) -> Decimal | None:
    """Like `_to_decimal`, but returns None instead of raising."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Data models
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MarketStat:
    """A snapshot for one trading pair, e.g. BTCTMN.

    `Decimal` is used for every price/volume so no precision is lost. Values
    the API did not supply are `None` rather than a misleading `0`.
    """

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
        """Build from one entry of `/v1/market-status`.

        Field names vary between `snake_case` and `camelCase` in Wallex
        payloads, so each value is looked up under several names.
        """
        stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else raw

        return cls(
            symbol=symbol,
            last_price=_optional_decimal(
                _pick(stats, "lastPrice", "last_price", "price")
            ),
            price_change_24h=_optional_decimal(
                _pick(stats, "priceChange", "price_change", "change")
            ),
            price_change_percent_24h=_optional_decimal(
                _pick(
                    stats,
                    "priceChangePercent",
                    "price_change_percent",
                    "change_percent",
                )
            ),
            high_24h=_optional_decimal(
                _pick(stats, "highPrice", "high_price", "high")
            ),
            low_24h=_optional_decimal(
                _pick(stats, "lowPrice", "low_price", "low")
            ),
            volume_24h=_optional_decimal(
                _pick(stats, "volume", "base_volume", "volume_24h")
            ),
            quote_volume_24h=_optional_decimal(
                _pick(stats, "quoteVolume", "quote_volume", "volume_tmn")
            ),
            best_bid=_optional_decimal(
                _pick(raw, "best_bid", "bestBid", "bid")
            ),
            best_ask=_optional_decimal(
                _pick(raw, "best_ask", "bestAsk", "ask")
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        """Plain, JSON-friendly representation (Decimals become strings)."""
        return {
            "symbol": self.symbol,
            "last_price": _str_or_none(self.last_price),
            "price_change_24h": _str_or_none(self.price_change_24h),
            "price_change_percent_24h": _str_or_none(
                self.price_change_percent_24h
            ),
            "high_24h": _str_or_none(self.high_24h),
            "low_24h": _str_or_none(self.low_24h),
            "volume_24h": _str_or_none(self.volume_24h),
            "quote_volume_24h": _str_or_none(self.quote_volume_24h),
            "best_bid": _str_or_none(self.best_bid),
            "best_ask": _str_or_none(self.best_ask),
        }


def _str_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


@dataclass(frozen=True)
class Candle:
    """One OHLC candle. All times are UTC."""

    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class MarketClient:
    """Read-only access to Wallex public market data.

    Example:
        >>> with MarketClient.from_settings() as client:      # doctest: +SKIP
        ...     print(client.get_ticker("BTCTMN").last_price)
    """

    def __init__(self, http: WallexHttpClient) -> None:
        self._http = http

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "MarketClient":
        """Build a client from the app configuration.

        No API key is used here, even if one is configured -- public data
        should never depend on a credential.

        The transport is wrapped in `ReadOnlyClient` for consistency with the
        account client, so *every* request this application makes passes the
        same allowlist. It costs nothing and means there is one rule, not two.
        """
        settings = settings or get_settings()
        http = WallexHttpClient(
            base_url=settings.wallex_base_url,
            api_key=None,
            timeout=settings.request_timeout,
            max_retries=settings.max_retries,
        )
        return cls(ReadOnlyClient(http))

    # ------------------------------------------------------------------ #
    # Endpoints
    # ------------------------------------------------------------------ #
    def get_markets(self) -> dict[str, dict[str, Any]]:
        """All tradeable symbols, keyed by symbol (e.g. "BTCTMN").

        This is the "what can I quote?" list. Kept as raw dicts because
        different callers want different fields; use `get_market_stats()` for
        parsed numbers.
        """
        result = self._http.get("/v1/markets")
        markets = result.get("symbols") or result.get("markets") or result

        if not isinstance(markets, dict):
            raise WallexResponseError(
                "Expected /v1/markets to contain a mapping of symbols, "
                f"got {type(markets).__name__}. Run --probe to inspect."
            )

        logger.debug("Fetched %d markets", len(markets))
        return markets

    def list_symbols(self) -> list[str]:
        """Sorted list of available symbol names."""
        return sorted(self.get_markets().keys())

    def get_market_stats(self) -> list[MarketStat]:
        """Parsed snapshot for every symbol."""
        result = self._http.get("/v1/market-status")
        raw_stats = result.get("symbols") or result.get("stats") or result

        if not isinstance(raw_stats, dict):
            raise WallexResponseError(
                "Expected /v1/market-status to contain a mapping of symbols, "
                f"got {type(raw_stats).__name__}. Run --probe to inspect."
            )

        parsed = [
            MarketStat.from_api(symbol, raw)
            for symbol, raw in raw_stats.items()
            if isinstance(raw, dict)
        ]
        logger.debug("Parsed %d market stats", len(parsed))
        return parsed

    def get_ticker(self, symbol: str) -> MarketStat:
        """Snapshot for a single symbol.

        Implemented on top of the bulk endpoint: Wallex has no per-symbol
        ticker, and one bulk call is cheaper than several single ones.
        """
        wanted = symbol.upper()
        for stat in self.get_market_stats():
            if stat.symbol.upper() == wanted:
                return stat
        raise WallexResponseError(
            f"Symbol {symbol!r} was not found in market data. "
            f"Check the exchange's available symbols with --probe."
        )

    def get_orderbook(self, symbol: str, *, limit: int = 20) -> dict[str, Any]:
        """Order book for `symbol`: bids (buyers) and asks (sellers).

        Returned as a dict with at least "bids" and "asks". Each side is a list
        of price/quantity pairs. Shapes vary by venue, so the raw structure is
        preserved -- `depth_summary()` flattens it for display.
        """
        result = self._http.get("/v1/depth", params={"symbol": symbol.upper()})
        book = result.get("depth") or result
        if not isinstance(book, dict) or "bids" not in book:
            raise WallexResponseError(
                "/v1/depth did not contain a 'bids'/'asks' structure. "
                "Run --probe to inspect."
            )
        for side in ("bids", "asks"):
            if isinstance(book.get(side), list):
                book[side] = book[side][:limit]
        return book

    def get_trades(self, symbol: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Most recent public trades for `symbol`."""
        result = self._http.get(
            "/v1/trades", params={"symbol": symbol.upper()}
        )
        trades = result.get("trades") or result.get("lastTrade") or result
        if isinstance(trades, dict):
            trades = trades.get("trades", [])
        if not isinstance(trades, list):
            raise WallexResponseError(
                "Expected /v1/trades to return a list. Run --probe to inspect."
            )
        return trades[:limit]

    def get_ohlc(
        self,
        symbol: str,
        *,
        resolution: int = 60,
        days: int = 7,
        end: datetime | None = None,
    ) -> list[Candle]:
        """OHLC candle history.

        Wallex serves this through a TradingView-style "UDF" endpoint, which
        returns *parallel arrays* rather than a list of objects:

            {"s": "ok", "t": [..], "o": [..], "h": [..], "l": [..],
             "c": [..], "v": [..]}

        so "the candle at index 3" is t[3], o[3], h[3], l[3], c[3], v[3].
        `_candles_from_udf()` turns that into proper `Candle` objects.

        Args:
            resolution: Candle size in minutes (1, 5, 15, 60, 240, 1440).
            days: How far back to fetch.
            end: Exclusive end time; defaults to now.
        """
        end_dt = end or datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=days)

        result = self._http.get(
            "/v1/udf/history",
            params={
                "symbol": symbol.upper(),
                "resolution": str(resolution),
                "from": str(int(start_dt.timestamp())),
                "to": str(int(end_dt.timestamp())),
            },
        )
        return self._candles_from_udf(result, symbol)

    @staticmethod
    def _candles_from_udf(payload: dict[str, Any], symbol: str) -> list[Candle]:
        """Convert the parallel-array payload into `Candle` objects."""
        status = payload.get("s")
        if status == "no_data":
            logger.info("No candle data available for %s", symbol)
            return []
        if status not in (None, "ok"):
            raise WallexResponseError(
                f"UDF history returned status {status!r} for {symbol}"
            )

        times = payload.get("t") or []
        opens = payload.get("o") or []
        highs = payload.get("h") or []
        lows = payload.get("l") or []
        closes = payload.get("c") or []
        volumes = payload.get("v") or []

        if not all(
            isinstance(seq, list)
            for seq in (times, opens, highs, lows, closes)
        ):
            raise WallexResponseError(
                "UDF history fields t/o/h/l/c must all be lists. "
                "Run --probe to inspect."
            )

        # Guard against ragged arrays: take the shortest series.
        count = min(len(times), len(opens), len(highs), len(lows), len(closes))
        candles: list[Candle] = []
        for i in range(count):
            try:
                candles.append(
                    Candle(
                        open_time=datetime.fromtimestamp(
                            int(times[i]), tz=timezone.utc
                        ),
                        open=Decimal(str(opens[i])),
                        high=Decimal(str(highs[i])),
                        low=Decimal(str(lows[i])),
                        close=Decimal(str(closes[i])),
                        volume=_optional_decimal(
                            volumes[i] if i < len(volumes) else None
                        ),
                    )
                )
            except (ValueError, TypeError, InvalidOperation) as exc:
                logger.warning(
                    "Skipping malformed candle %d for %s: %s", i, symbol, exc
                )
        return candles

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "MarketClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


# --------------------------------------------------------------------------- #
# Probe mode -- run this first against the real API
# --------------------------------------------------------------------------- #
PROBE_ENDPOINTS: tuple[tuple[str, dict[str, Any] | None], ...] = (
    ("/v1/markets", None),
    ("/v1/market-status", None),
    ("/v1/depth", {"symbol": "BTCTMN"}),
    ("/v1/trades", {"symbol": "BTCTMN"}),
)


def _truncate(value: Any, max_items: int = 2) -> Any:
    """Shrink large payloads so the probe output stays readable."""
    if isinstance(value, list):
        return [value[:max_items], f"... ({len(value)} items total)"]
    if isinstance(value, dict):
        return {
            k: _truncate(v, max_items) if isinstance(v, (list, dict)) else v
            for k, v in list(value.items())[:15]
        }
    return value


def probe(settings: Settings) -> int:
    """Fetch each public endpoint and print its raw JSON structure.

    This exists because I will not build parsing logic on guessed field names.
    Read the output, and the real names are visible immediately.
    """
    client = MarketClient.from_settings(settings)
    exit_code = 0
    try:
        for path, params in PROBE_ENDPOINTS:
            label = path + (f"?{params}" if params else "")
            print(f"\n{'=' * 70}\nGET {label}\n{'=' * 70}")
            try:
                payload = client._http.get(path, params=params)  # noqa: SLF001
                print(json.dumps(_truncate(payload), indent=2, default=str)[:3000])
            except WallexError as exc:
                exit_code = 1
                print(f"FAILED: {exc}")
    finally:
        client.close()
    return exit_code


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.

        python -m wallex_assistant.market_client --probe
        python -m wallex_assistant.market_client --ticker BTCTMN
        python -m wallex_assistant.market_client --symbols
    """
    parser = argparse.ArgumentParser(
        description="Inspect Wallex public market data (read-only)."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--probe", action="store_true",
        help="Dump the raw JSON of each public endpoint.",
    )
    group.add_argument(
        "--ticker", metavar="SYMBOL", help="Show the snapshot for one symbol."
    )
    group.add_argument(
        "--symbols", action="store_true", help="List available symbols."
    )
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"Configuration error:\n{exc}", file=sys.stderr)
        return 2

    setup_logging(settings.log_level, log_to_file=False)

    if args.probe:
        return probe(settings)

    client = MarketClient.from_settings(settings)
    try:
        if args.symbols:
            symbols = client.list_symbols()
            print(f"{len(symbols)} symbols available:")
            for symbol in symbols:
                print(f"  {symbol}")
        elif args.ticker:
            stat = client.get_ticker(args.ticker)
            print(f"Symbol            : {stat.symbol}")
            print(f"Last price        : {stat.last_price}")
            print(f"24h change        : {stat.price_change_percent_24h}%")
            print(f"24h high / low    : {stat.high_24h} / {stat.low_24h}")
            print(f"24h volume        : {stat.volume_24h}")
    except WallexError as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
