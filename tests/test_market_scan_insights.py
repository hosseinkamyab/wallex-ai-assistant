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


def dated_history(count=260, bullish=False):
    start = datetime.now(timezone.utc) - timedelta(days=count)
    price = 100.0
    rows = []
    for i in range(count):
        price += 0.1 if bullish else -0.45
        rows.append(Candle(
            start + timedelta(days=i),
            Decimal(str(price)),
            Decimal(str(price + 1)),
            Decimal(str(price - 1)),
            Decimal(str(price)),
            Decimal("1000"),
        ))
    return rows


class TestMarketScanInsights(unittest.TestCase):
    def test_bearish_market_is_diagnosed_without_adding_opportunities(self):
        history = {"BTCTMN": {"1d": dated_history(count=260, bullish=False)}}
        opportunities = BuyOpportunityScanner(max_candle_age_days=3).scan(["BTCTMN"], history)
        diagnostics = diagnose_buy_rejections(["BTCTMN"], history)

        self.assertEqual(opportunities, [])
        self.assertGreater(diagnostics["counts"].get("no_bullish_trend", 0), 0)
        self.assertIn("no_bullish_trend", REASON_LABELS)

    def test_insufficient_history_is_diagnosed(self):
        history = {"BTCTMN": {"1d": dated_history(count=49, bullish=False)}}
        diagnostics = diagnose_buy_rejections(["BTCTMN"], history)
        self.assertEqual(diagnostics["counts"].get("insufficient_history"), 1)

    def test_missing_history_is_diagnosed(self):
        diagnostics = diagnose_buy_rejections(["BTCTMN"], {})
        self.assertEqual(diagnostics["counts"].get("insufficient_history"), 1)

    def test_dynamic_context_explanation_changes_by_market(self):
        class BearishContext:
            btc_direction = "bearish"
            breadth = 0.25
            volatility = "high"
            risk_condition = "elevated"

        text = market_condition_explanation(BearishContext())
        self.assertIn("unfavorable", text)

        class BullishLimitedContext:
            btc_direction = "bullish"
            breadth = 0.25
            volatility = "normal"
            risk_condition = "constructive"

        text = market_condition_explanation(BullishLimitedContext())
        self.assertIn("limited", text)


if __name__ == "__main__":
    unittest.main()
