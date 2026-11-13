"""Offline tests for the BUY opportunity detection module."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from wallex_assistant.buy_opportunity import BuyOpportunityScanner, recommend_best_buy
from wallex_assistant.market_client import Candle


def bullish_history(count=260):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = 100.0
    rows = []
    for index in range(count):
        price += 0.35 if index % 5 else 0.12
        rows.append(
            Candle(
                start + timedelta(days=index),
                Decimal(str(price - 0.5)),
                Decimal(str(price + 1.2)),
                Decimal(str(price - 1.1)),
                Decimal(str(price)),
                Decimal(str(1_200_000 + index * 2000)),
            )
        )
    return rows


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


if __name__ == "__main__":
    unittest.main()

