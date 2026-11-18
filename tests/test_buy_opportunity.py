"""Offline tests for the BUY opportunity detection module."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from types import SimpleNamespace

from wallex_assistant.buy_opportunity import (
    BuyOpportunityScanner,
    _compute_risk_reward,
    _entry_range,
    _normalize_symbol,
    _stop_and_targets,
    _support_resistance,
    _valid_candles,
    recommend_best_buy,
)
from wallex_assistant.market_client import Candle


def make_history(count=260, *, bullish=True, volume=1_000_000, upper_wick=0.3):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    price = 100.0
    rows = []
    for index in range(count):
        previous = price
        if bullish:
            price += -1.8 if index % 5 == 0 else 0.8
            candle_volume = volume * (1.8 if index == count - 1 else 1.0)
        else:
            price -= 0.45 if index % 4 else 0.25
            candle_volume = volume
        rows.append(Candle(
            open_time=start + timedelta(days=index),
            open=Decimal(str(previous)),
            high=Decimal(str(max(previous, price) + upper_wick)),
            low=Decimal(str(max(0.01, min(previous, price) - 1.1))),
            close=Decimal(str(max(0.01, price))),
            volume=Decimal(str(candle_volume)),
        ))
    return rows


class TestBuyOpportunity(unittest.TestCase):
    def test_bullish_history_generates_ranked_opportunity(self):
        history = {"BTC/TMN": {"1d": make_history(bullish=True)}}
        ranked = BuyOpportunityScanner().scan(["btc-tmn"], history)
        self.assertTrue(ranked)
        self.assertGreaterEqual(ranked[0].confidence_score, 60.0)

    def test_bearish_history_returns_wait(self):
        history = {"BTCTMN": {"1d": make_history(bullish=False)}}
        signal, symbol, ranked = recommend_best_buy(None, ["BTCTMN"], history)
        self.assertEqual(signal, "WAIT")
        self.assertIsNone(symbol)
        self.assertEqual(ranked, [])

    def test_insufficient_history_is_rejected(self):
        history = {"BTCTMN": {"1d": make_history(count=49)}}
        self.assertEqual(BuyOpportunityScanner().scan(["BTCTMN"], history), [])

    def test_malformed_and_nonfinite_candles_are_filtered(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        candles = [
            Candle(start, Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1000")),
            Candle(start + timedelta(days=1), Decimal("100"), Decimal("50"), Decimal("90"), Decimal("95"), Decimal("1000")),
            Candle(start + timedelta(days=2), Decimal("NaN"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1000")),
        ]
        valid = _valid_candles(candles)
        self.assertEqual(len(valid), 1)

    def test_quote_volume_above_threshold_is_accepted(self):
        class FakeClient:
            def get_ticker(self, symbol):
                return SimpleNamespace(quote_volume_24h=Decimal("2_000_000_000"))
        ranked = BuyOpportunityScanner(FakeClient(), min_quote_volume_24h=1_000_000_000).scan(
            ["BTCTMN"], {"BTCTMN": {"1d": make_history()}})
        self.assertTrue(ranked)

    def test_quote_volume_below_threshold_is_rejected(self):
        class FakeClient:
            def get_ticker(self, symbol):
                return SimpleNamespace(quote_volume_24h=Decimal("500000000"))
        ranked = BuyOpportunityScanner(FakeClient(), min_quote_volume_24h=1_000_000_000).scan(
            ["BTCTMN"], {"BTCTMN": {"1d": make_history()}})
        self.assertEqual(ranked, [])

    def test_missing_quote_volume_is_rejected_when_threshold_is_configured(self):
        class FakeClient:
            def get_ticker(self, symbol):
                return SimpleNamespace(quote_volume_24h=None)
        ranked = BuyOpportunityScanner(FakeClient(), min_quote_volume_24h=1_000_000_000).scan(
            ["BTCTMN"], {"BTCTMN": {"1d": make_history()}})
        self.assertEqual(ranked, [])

    def test_ticker_exception_is_treated_as_unavailable(self):
        class FakeClient:
            def get_ticker(self, symbol):
                raise RuntimeError("simulated API failure")
        ranked = BuyOpportunityScanner(FakeClient(), min_quote_volume_24h=1_000_000_000).scan(
            ["BTCTMN"], {"BTCTMN": {"1d": make_history()}})
        self.assertEqual(ranked, [])

    def test_symbol_normalization_does_not_rewrite_quote_currency(self):
        self.assertEqual(_normalize_symbol("btc/usdt"), "BTCUSDT")
        self.assertEqual(_normalize_symbol("btc-tmn"), "BTCTMN")
        self.assertEqual(_normalize_symbol("BTC TMN"), "BTCTMN")
        self.assertEqual(_normalize_symbol("../bad"), "")
        self.assertEqual(_normalize_symbol("USDT"), "USDT")

    def test_support_resistance_finds_window_extremes(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        candles = [Candle(start + timedelta(days=i), Decimal("100"), Decimal(str(115 if i == 1 else 105)), Decimal(str(90 if i == 0 else 95)), Decimal("100"), Decimal("1000")) for i in range(2)]
        support, resistance = _support_resistance(candles)
        self.assertEqual(support, 90.0)
        self.assertEqual(resistance, 115.0)

    def test_risk_reward_rejects_invalid_buy_levels(self):
        self.assertEqual(_compute_risk_reward(100, 105, 110, 120), 0.0)
        self.assertEqual(_compute_risk_reward(100, 90, 85, 120), 0.0)
        self.assertEqual(_compute_risk_reward(100, 90, 120, 110), 0.0)

    def test_risk_reward_calculates_valid_buy_levels(self):
        self.assertEqual(_compute_risk_reward(100, 90, 120, 130), 2.5)

    def test_entry_range_and_stop_target_ordering(self):
        low, high = _entry_range(opportunity_type="support-level rebounds", price=100, support=95, resistance=105)
        self.assertLessEqual(low, high)
        stop, target_1, target_2 = _stop_and_targets(
            price=100, support=95, resistance=105,
            opportunity_type="support-level rebounds", atr=2,
            entry_low=low, entry_high=high)
        self.assertLess(stop, low)
        self.assertGreater(target_1, high)
        self.assertGreater(target_2, target_1)

    def test_nearby_resistance_with_insufficient_reward_is_rejected(self):
        # A large upper wick puts resistance just above the entry band. The
        # scanner should keep rejecting this setup on its risk/reward filter.
        history = {"BTCTMN": {"1d": make_history(upper_wick=1.2)}}
        self.assertEqual(BuyOpportunityScanner().scan(["BTCTMN"], history), [])

    def test_stale_history_rejected_when_configured(self):
        old = make_history()
        history = {"BTCTMN": {"1d": old}}
        ranked = BuyOpportunityScanner(max_candle_age_days=1).scan(["BTCTMN"], history)
        self.assertEqual(ranked, [])

    def test_multiple_symbols_have_deterministic_ranking(self):
        history = {
            "ETHUSDT": {"1d": make_history(bullish=True)},
            "BTCUSDT": {"1d": make_history(bullish=True)},
            "NOPETMN": {"1d": make_history(bullish=False)},
        }
        ranked = BuyOpportunityScanner().scan(["ETHUSDT", "BTCUSDT", "NOPETMN"], history)
        symbols = [item.symbol for item in ranked]
        repeated = [item.symbol for item in BuyOpportunityScanner().scan(["ETHUSDT", "BTCUSDT", "NOPETMN"], history)]
        self.assertEqual(symbols, repeated)
        self.assertEqual(len(symbols), len(set(symbols)))


if __name__ == "__main__":
    unittest.main()
