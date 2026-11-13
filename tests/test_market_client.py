"""Tests for the public market-data client.

The HTTP layer is faked, so these run offline and instantly.
"""

from __future__ import annotations

import unittest
from datetime import timezone
from decimal import Decimal
from unittest import mock

from wallex_assistant.errors import WallexResponseError
from wallex_assistant.market_client import (
    Candle,
    MarketClient,
    MarketStat,
    _optional_decimal,
    _pick,
    _to_decimal,
)


def _client_with(payload, *, path_ok: str | None = None) -> MarketClient:
    """A MarketClient whose HTTP layer returns `payload`."""
    http = mock.Mock()
    http.get.return_value = payload
    return MarketClient(http)


class TestHelpers(unittest.TestCase):
    def test_pick_returns_first_present_key(self) -> None:
        data = {"last_price": Decimal("5")}
        self.assertEqual(_pick(data, "lastPrice", "last_price"), Decimal("5"))

    def test_pick_skips_none_values(self) -> None:
        data = {"lastPrice": None, "last_price": Decimal("7")}
        self.assertEqual(_pick(data, "lastPrice", "last_price"), Decimal("7"))

    def test_pick_returns_none_when_absent(self) -> None:
        self.assertIsNone(_pick({}, "a", "b"))

    def test_to_decimal_parses_strings(self) -> None:
        # APIs send prices as strings to avoid float precision loss.
        self.assertEqual(_to_decimal("1.23", "price", "t"), Decimal("1.23"))

    def test_to_decimal_rejects_missing_field(self) -> None:
        with self.assertRaises(WallexResponseError) as ctx:
            _to_decimal(None, "price", "market BTCTMN")
        self.assertIn("price", str(ctx.exception))

    def test_to_decimal_rejects_non_numeric(self) -> None:
        with self.assertRaises(WallexResponseError):
            _to_decimal("abc", "price", "t")

    def test_optional_decimal_tolerates_junk(self) -> None:
        self.assertIsNone(_optional_decimal(""))
        self.assertIsNone(_optional_decimal("abc"))
        self.assertIsNone(_optional_decimal(None))
        self.assertEqual(_optional_decimal("2.5"), Decimal("2.5"))


class TestMarketStatParsing(unittest.TestCase):
    def test_camel_case_fields(self) -> None:
        stat = MarketStat.from_api(
            "BTCTMN",
            {
                "stats": {
                    "lastPrice": "1000",
                    "priceChangePercent": "2.5",
                    "highPrice": "1100",
                    "lowPrice": "900",
                    "volume": "12.5",
                }
            },
        )
        self.assertEqual(stat.symbol, "BTCTMN")
        self.assertEqual(stat.last_price, Decimal("1000"))
        self.assertEqual(stat.price_change_percent_24h, Decimal("2.5"))
        self.assertEqual(stat.high_24h, Decimal("1100"))
        self.assertEqual(stat.low_24h, Decimal("900"))
        self.assertEqual(stat.volume_24h, Decimal("12.5"))

    def test_snake_case_fields_also_work(self) -> None:
        stat = MarketStat.from_api(
            "ETHTMN", {"last_price": "50", "price_change_percent": "1.0"}
        )
        self.assertEqual(stat.last_price, Decimal("50"))
        self.assertEqual(stat.price_change_percent_24h, Decimal("1.0"))

    def test_missing_fields_become_none_not_zero(self) -> None:
        # A missing price must not silently become 0 -- that would badly
        # distort portfolio totals.
        stat = MarketStat.from_api("XXXTMN", {})
        self.assertIsNone(stat.last_price)
        self.assertIsNone(stat.volume_24h)

    def test_best_bid_ask_read_from_top_level(self) -> None:
        stat = MarketStat.from_api(
            "BTCTMN", {"stats": {}, "best_bid": "99", "best_ask": "101"}
        )
        self.assertEqual(stat.best_bid, Decimal("99"))
        self.assertEqual(stat.best_ask, Decimal("101"))

    def test_as_dict_is_json_friendly(self) -> None:
        stat = MarketStat.from_api("BTCTMN", {"stats": {"lastPrice": "5"}})
        data = stat.as_dict()
        self.assertEqual(data["last_price"], "5")  # string, not Decimal
        self.assertIsNone(data["volume_24h"])


class TestMarkets(unittest.TestCase):
    def test_get_markets_returns_symbol_mapping(self) -> None:
        client = _client_with({"symbols": {"BTCTMN": {"base": "BTC"}}})
        markets = client.get_markets()
        self.assertIn("BTCTMN", markets)

    def test_list_symbols_is_sorted(self) -> None:
        client = _client_with({"symbols": {"ZZZTMN": {}, "AAATMN": {}}})
        self.assertEqual(client.list_symbols(), ["AAATMN", "ZZZTMN"])

    def test_get_markets_rejects_wrong_shape(self) -> None:
        client = _client_with({"symbols": ["not", "a", "dict"]})
        with self.assertRaises(WallexResponseError):
            client.get_markets()


class TestMarketStats(unittest.TestCase):
    def test_stats_are_parsed(self) -> None:
        client = _client_with(
            {"symbols": {"BTCTMN": {"stats": {"lastPrice": "100"}}}}
        )
        stats = client.get_market_stats()
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0].symbol, "BTCTMN")
        self.assertEqual(stats[0].last_price, Decimal("100"))

    def test_non_dict_entries_are_skipped(self) -> None:
        client = _client_with(
            {
                "symbols": {
                    "BTCTMN": {"stats": {"lastPrice": "100"}},
                    "BROKEN": "not a dict",
                }
            }
        )
        self.assertEqual(len(client.get_market_stats()), 1)

    def test_get_ticker_finds_symbol_case_insensitively(self) -> None:
        client = _client_with(
            {"symbols": {"BTCTMN": {"stats": {"lastPrice": "100"}}}}
        )
        self.assertEqual(client.get_ticker("btctmn").last_price, Decimal("100"))

    def test_get_ticker_raises_for_unknown_symbol(self) -> None:
        client = _client_with({"symbols": {"BTCTMN": {"stats": {}}}})
        with self.assertRaises(WallexResponseError) as ctx:
            client.get_ticker("NOPETMN")
        self.assertIn("NOPETMN", str(ctx.exception))


class TestOrderbookAndTrades(unittest.TestCase):
    def test_orderbook_limits_depth(self) -> None:
        bids = [[str(i), "1"] for i in range(100)]
        client = _client_with({"bids": bids, "asks": bids})
        book = client.get_orderbook("BTCTMN", limit=5)
        self.assertEqual(len(book["bids"]), 5)
        self.assertEqual(len(book["asks"]), 5)

    def test_orderbook_rejects_wrong_shape(self) -> None:
        client = _client_with({"unexpected": True})
        with self.assertRaises(WallexResponseError):
            client.get_orderbook("BTCTMN")

    def test_trades_returns_list(self) -> None:
        client = _client_with({"trades": [{"price": "1"}, {"price": "2"}]})
        self.assertEqual(len(client.get_trades("BTCTMN")), 2)

    def test_trades_limits_results(self) -> None:
        client = _client_with({"trades": [{"p": i} for i in range(100)]})
        self.assertEqual(len(client.get_trades("BTCTMN", limit=10)), 10)

    def test_trades_rejects_wrong_shape(self) -> None:
        client = _client_with({"trades": "nope"})
        with self.assertRaises(WallexResponseError):
            client.get_trades("BTCTMN")


class TestCandles(unittest.TestCase):
    def test_parallel_arrays_become_candles(self) -> None:
        payload = {
            "s": "ok",
            "t": [1700000000, 1700000060],
            "o": [100, 101],
            "h": [110, 111],
            "l": [90, 91],
            "c": [105, 106],
            "v": [1.5, 2.5],
        }
        candles = MarketClient._candles_from_udf(payload, "BTCTMN")
        self.assertEqual(len(candles), 2)
        first = candles[0]
        self.assertIsInstance(first, Candle)
        self.assertEqual(first.open, Decimal("100"))
        self.assertEqual(first.close, Decimal("105"))
        self.assertEqual(first.volume, Decimal("1.5"))
        self.assertEqual(first.open_time.tzinfo, timezone.utc)

    def test_no_data_returns_empty_list(self) -> None:
        self.assertEqual(
            MarketClient._candles_from_udf({"s": "no_data"}, "BTCTMN"), []
        )

    def test_unexpected_status_raises(self) -> None:
        with self.assertRaises(WallexResponseError):
            MarketClient._candles_from_udf({"s": "error"}, "BTCTMN")

    def test_ragged_arrays_are_truncated_safely(self) -> None:
        # Fewer closes than opens: must take the shortest, not crash.
        payload = {
            "s": "ok", "t": [1, 2, 3], "o": [1, 2, 3],
            "h": [1, 2, 3], "l": [1, 2], "c": [1, 2],
        }
        self.assertEqual(
            len(MarketClient._candles_from_udf(payload, "X")), 2
        )

    def test_missing_volume_is_tolerated(self) -> None:
        payload = {
            "s": "ok", "t": [1], "o": [1], "h": [1], "l": [1], "c": [1],
        }
        candles = MarketClient._candles_from_udf(payload, "X")
        self.assertIsNone(candles[0].volume)


class TestNoCredentialUse(unittest.TestCase):
    def test_market_client_never_sends_a_key(self) -> None:
        # Public data must not depend on a credential.
        from wallex_assistant.config import Settings

        settings = Settings(wallex_api_key="SHOULD-NOT-BE-USED")
        client = MarketClient.from_settings(settings)
        self.addCleanup(client.close)
        self.assertNotIn(
            "x-api-key", client._http._session.headers  # noqa: SLF001
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
