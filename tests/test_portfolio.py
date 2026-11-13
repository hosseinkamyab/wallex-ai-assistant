"""Tests for portfolio valuation and analysis helpers."""

from __future__ import annotations

import unittest
from decimal import Decimal
from unittest import mock

from wallex_assistant.account_client import Balance
from wallex_assistant.config import Settings
from wallex_assistant.market_client import MarketStat
from wallex_assistant.portfolio import (
    generate_analysis,
    get_asset_values,
    value_portfolio,
)


class TestPortfolioValuation(unittest.TestCase):
    def test_value_portfolio_uses_matching_prices(self) -> None:
        balances = [
            Balance(asset="BTC", available=Decimal("1"), locked=Decimal("0.5")),
            Balance(asset="ETH", available=Decimal("2"), locked=Decimal("0")),
        ]
        market_stats = [
            MarketStat(symbol="BTC", last_price=Decimal("1000")),
            MarketStat(symbol="ETH", last_price=Decimal("500")),
        ]

        self.assertEqual(value_portfolio(balances, market_stats), Decimal("2000"))

    def test_value_portfolio_ignores_assets_without_market_price(self) -> None:
        balances = [
            Balance(asset="BTC", available=Decimal("1")),
            Balance(asset="MOON", available=Decimal("10")),
        ]
        market_stats = [MarketStat(symbol="BTC", last_price=Decimal("1000"))]

        self.assertEqual(value_portfolio(balances, market_stats), Decimal("1000"))

    def test_get_asset_values_sorts_by_value(self) -> None:
        balances = [
            Balance(asset="ETH", available=Decimal("1")),
            Balance(asset="BTC", available=Decimal("2")),
        ]
        market_stats = [
            MarketStat(symbol="ETH", last_price=Decimal("100")),
            MarketStat(symbol="BTC", last_price=Decimal("200")),
        ]

        values = get_asset_values(balances, market_stats)
        self.assertEqual([item["asset"] for item in values], ["BTC", "ETH"])


class TestGenerateAnalysis(unittest.TestCase):
    def test_generate_analysis_uses_deterministic_summary_when_mock(self) -> None:
        balances = [Balance(asset="BTC", available=Decimal("1"))]
        market_stats = [MarketStat(symbol="BTC", last_price=Decimal("1000"))]

        with mock.patch(
            "wallex_assistant.config.Settings.load",
            return_value=Settings(llm_provider="mock"),
        ):
            result = generate_analysis(balances=balances, market_stats=market_stats)

        self.assertIn("Total portfolio value", result)
        self.assertIn("BTC", result)

    def test_generate_analysis_empty_balances_returns_empty_message(self) -> None:
        with mock.patch(
            "wallex_assistant.config.Settings.load",
            return_value=Settings(llm_provider="mock"),
        ):
            result = generate_analysis(balances=[], market_stats=[])

        self.assertIn("No analysis yet", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
