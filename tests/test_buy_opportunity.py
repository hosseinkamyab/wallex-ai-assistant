"""Offline tests for the BUY opportunity detection module."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest
from types import SimpleNamespace

from wallex_assistant.buy_opportunity import (
    BuyOpportunityScanner,
    _support_resistance,
    recommend_best_buy,
    _compute_risk_reward,
    _stop_and_targets
)
from wallex_assistant.market_client import Candle


def bullish_history(count=260):
    candles = []
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = 100.0

    for index in range(count):
        previous_price = price

        # Overall upward trend with regular pullbacks
        price += -1.8 if index % 5 == 0 else 0.5

        volume = 1_000_000 + (index % 7) * 1_000

        # Add stronger volume on the latest candle
        if index == count - 1:
            volume = 1_800_000

        candles.append(
            Candle(
                open_time=start + timedelta(days=index),
                open=Decimal(str(previous_price)),
                high=Decimal(str(max(previous_price, price) + 1.2)),
                low=Decimal(str(min(previous_price, price) - 1.1)),
                close=Decimal(str(price)),
                volume=Decimal(str(volume)),
            )
        )

    return candles


def bearish_history(count=260):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = 150.0
    rows = []
    for index in range(count):
        price -= 0.32 if index % 4 else 0.18
        rows.append(
            Candle(
                start + timedelta(days=index),
                Decimal(str(price - 0.4)),
                Decimal(str(price + 1.0)),
                Decimal(str(price - 1.2)),
                Decimal(str(price)),
                Decimal(str(900_000 + index * 1500)),
            )
        )
    return rows


class TestBuyOpportunity(unittest.TestCase):
    def test_bullish_history_generates_ranked_buy_opportunity(self):
        history = {"BTCTMN": {"1d": bullish_history()}}
        ranked = BuyOpportunityScanner().scan(["BTCTMN"], history)
        self.assertTrue(ranked)
        self.assertGreaterEqual(ranked[0].confidence_score, 60.0)
        self.assertIn(ranked[0].opportunity_type, {
            "trend-following entries",
            "support-level rebounds",
            "pullback opportunities",
            "oversold recovery opportunities",
            "long-term accumulation opportunities",
            "breakout opportunities",
        })

    def test_bearish_history_returns_wait(self):
        history = {"BTCTMN": {"1d": bearish_history()}}
        signal, symbol, ranked = recommend_best_buy(None, ["BTCTMN"], history)
        self.assertEqual(signal, "WAIT")
        self.assertIsNone(symbol)
        self.assertEqual(ranked, [])

    def test_quote_volume_above_threshold_is_accepted(self):
        class FakeMarketClient:
            def get_ticker(self, symbol):
                return SimpleNamespace(
                    quote_volume_24h=Decimal("2000000000")
                )

        history = {"BTCTMN": {"1d": bullish_history()}}
        scanner = BuyOpportunityScanner(
            market_client=FakeMarketClient(),
            min_quote_volume_24h=1_000_000_000,
        )

        ranked = scanner.scan(["BTCTMN"], history)
        self.assertTrue(ranked)

    def test_quote_volume_below_threshold_is_rejected(self):
        class FakeMarketClient:
            def get_ticker(self, symbol):
                return SimpleNamespace(
                    quote_volume_24h=Decimal("500000000")
                )

        history = {"BTCTMN": {"1d": bullish_history()}}
        scanner = BuyOpportunityScanner(
            market_client=FakeMarketClient(),
            min_quote_volume_24h=1_000_000_000,
        )

        ranked = scanner.scan(["BTCTMN"], history)
        self.assertEqual(ranked, [])

    def test_missing_quote_volume_is_rejected_when_threshold_is_configured(self):
        class FakeMarketClient:
            def get_ticker(self, symbol):
                return SimpleNamespace(quote_volume_24h=None)

        history = {"BTCTMN": {"1d": bullish_history()}}
        scanner = BuyOpportunityScanner(
            market_client=FakeMarketClient(),
            min_quote_volume_24h=1_000_000_000,
        )

        ranked = scanner.scan(["BTCTMN"], history)
        self.assertEqual(ranked, [])

    def test_support_resistance_uses_candle_lows_and_highs(self):
        candles = [
            Candle(
                open_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                open=Decimal("100"),
                high=Decimal("115"),
                low=Decimal("90"),
                close=Decimal("105"),
                volume=Decimal("1000"),
            ),
            Candle(
                open_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
                open=Decimal("105"),
                high=Decimal("125"),
                low=Decimal("95"),
                close=Decimal("110"),
                volume=Decimal("1000"),
            ),
        ]

        support, resistance = _support_resistance(candles)

        self.assertEqual(support, 90.0)
        self.assertEqual(resistance, 125.0)
    def test_risk_reward_rejects_invalid_buy_levels(self):
        # Stop loss above entry
        self.assertEqual(
            _compute_risk_reward(100, 105, 110, 120),
            0.0,
        )

        # Target below entry
        self.assertEqual(
            _compute_risk_reward(100, 90, 85, 120),
            0.0,
        )

        # Target 2 below target 1
        self.assertEqual(
            _compute_risk_reward(100, 90, 120, 110),
            0.0,
        )

    def test_risk_reward_calculates_valid_buy_levels(self):
        result = _compute_risk_reward(100, 90, 120, 130)
        self.assertEqual(result, 2.5)

    def test_stop_and_targets_are_valid_for_buy_setup(self):
        stop, target_1, target_2 = _stop_and_targets(
            price=100.0,
            support=95.0,
            resistance=105.0,
            opportunity_type="support-level rebounds",
        )

        self.assertGreater(stop, 0)
        self.assertLess(stop, 100.0)
        self.assertGreater(target_1, 100.0)
        self.assertGreater(target_2, target_1)


if __name__ == "__main__":
    unittest.main()