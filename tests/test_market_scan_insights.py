"""Tests for deterministic Market Scan Insights diagnostics."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from wallex_assistant.buy_opportunity import BuyOpportunityScanner
from wallex_assistant.market_client import Candle
from wallex_assistant.market_scan_insights import (
    REASON_LABELS,
    diagnose_buy_rejections,
    market_condition_explanation,
)


def bearish_history(count=260):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    price = 100.0
    rows = []
    for i in range(count):
        price -= 0.45
        rows.append(Candle(start + timedelta(days=i), Decimal(str(price)), Decimal(str(price + 1)), Decimal(str(price - 1)), Decimal(str(price)), Decimal("1000")))
    return rows


class TestMarketScanInsights(unittest.TestCase):
    def test_bearish_market_is_diagnosed_without_adding_opportunities(self):
        history = {"BTCTMN": {"1d": bearish_history()}}
        scanner = BuyOpportunityScanner(max_candle_age_days=3)
        opportunities = scanner.scan(["BTCTMN"], history)
        diagnostics = diagnose_buy_rejections(["BTCTMN"], history)

        self.assertEqual(opportunities, [])
        self.assertGreater(diagnostics["counts"].get("no_bullish_trend", 0), 0)
        self.assertIn("no_bullish_trend", REASON_LABELS)

    def test_insufficient_history_is_diagnosed(self):
        history = {"BTCTMN": {"1d": bearish_history(49)}}
        diagnostics = diagnose_buy_rejections(["BTCTMN"], history)
        self.assertEqual(diagnostics["counts"].get("insufficient_history"), 1)

    def test_dynamic_context_explanation_changes_by_market(self):
        class Context:
            btc_direction = "bearish"
            breadth = 0.25
            volatility = "high"
            risk_condition = "elevated"

        text = market_condition_explanation(Context())
        self.assertIn("unfavorable", text)

        class BullishLimited(Context):
            btc_direction = "bullish"

        text = market_condition_explanation(BullishLimited())
        self.assertIn("limited", text)


if __name__ == "__main__":
    unittest.main()
