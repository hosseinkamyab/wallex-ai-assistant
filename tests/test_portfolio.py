"""Tests for portfolio valuation and analysis helpers."""

from __future__ import annotations

import unittest
from decimal import Decimal
from unittest import mock

from wallex_assistant.account_client import Balance
from wallex_assistant.config import Settings
from wallex_assistant.market_client import MarketStat, Candle
from wallex_assistant.portfolio import (
    generate_analysis,
    get_asset_values,
    value_portfolio,
    get_buy_opportunities,
    get_buy_opportunities_with_context,

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

        self.assertEqual(value_portfolio(balances, market_stats), Decimal("2500"))

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

class TestGetBuyOpportunities(unittest.TestCase):
    @mock.patch("wallex_assistant.buy_opportunity.BuyOpportunityScanner")
    @mock.patch("wallex_assistant.portfolio.MarketClient.from_settings")
    def test_selects_highest_volume_tmn_markets(
        self,
        mock_from_settings,
        mock_scanner_class,
    ) -> None:
        fake_client = mock.Mock()
        mock_from_settings.return_value = fake_client

        fake_client.get_market_stats.return_value = [
            MarketStat(
                symbol="BTCTMN",
                quote_volume_24h=Decimal("1000"),
            ),
            MarketStat(
                symbol="ETHTMN",
                quote_volume_24h=Decimal("3000"),
            ),
            MarketStat(
                symbol="SOLTMN",
                quote_volume_24h=Decimal("2000"),
            ),
            MarketStat(
                symbol="BTCUSDT",
                quote_volume_24h=Decimal("9000"),
            ),
        ]

        fake_client.get_history.return_value = []

        scanner = mock_scanner_class.return_value
        scanner.scan.return_value = []

        result = get_buy_opportunities(max_markets=2)

        self.assertEqual(result, [])
        scanner.scan.assert_called_once()

        scanned_symbols = scanner.scan.call_args.args[0]
        self.assertEqual(scanned_symbols, ["ETHTMN", "SOLTMN"])

        self.assertEqual(fake_client.get_history.call_count, 2)
        fake_client.close.assert_called_once()

    @mock.patch("wallex_assistant.portfolio.analyze_market")
    @mock.patch("wallex_assistant.buy_opportunity.BuyOpportunityScanner")
    @mock.patch("wallex_assistant.portfolio.MarketClient.from_settings")
    def test_returns_opportunities_and_market_context(
        self,
        mock_from_settings,
        mock_scanner_class,
        mock_analyze_market,
    ) -> None:
        fake_client = mock.Mock()
        mock_from_settings.return_value = fake_client

        fake_client.get_market_stats.return_value = [
            MarketStat(
                symbol="BTCTMN",
                quote_volume_24h=Decimal("3000"),
            ),
            MarketStat(
                symbol="ETHTMN",
                quote_volume_24h=Decimal("2000"),
            ),
        ]

        fake_client.get_history.return_value = candles_for_test()

        scanner = mock_scanner_class.return_value
        scanner.scan.return_value = ["BUY_TEST"]

        mock_analyze_market.return_value = ("MARKET_CONTEXT", [])

        opportunities, market_context = get_buy_opportunities_with_context(
            max_markets=2
        )

        self.assertEqual(opportunities, ["BUY_TEST"])
        self.assertEqual(market_context, "MARKET_CONTEXT")
        mock_analyze_market.assert_called_once()
        fake_client.close.assert_called_once()

    @mock.patch("wallex_assistant.analysis.analyze_market")
    @mock.patch("wallex_assistant.buy_opportunity.BuyOpportunityScanner")
    @mock.patch("wallex_assistant.portfolio.MarketClient.from_settings")
    def test_returns_opportunities_and_market_context(
        self,
        mock_from_settings,
        mock_scanner_class,
        mock_analyze_market,
    ) -> None:
        fake_client = mock.Mock()
        mock_from_settings.return_value = fake_client

        fake_client.get_market_stats.return_value = [
            MarketStat(
                symbol="BTCTMN",
                quote_volume_24h=Decimal("3000"),
            ),
            MarketStat(
                symbol="ETHTMN",
                quote_volume_24h=Decimal("2000"),
            ),
        ]

        fake_candles = [mock.Mock(), mock.Mock()]
        fake_client.get_history.return_value = fake_candles

        scanner = mock_scanner_class.return_value
        scanner.scan.return_value = ["BUY_TEST"]
        mock_analyze_market.return_value = ("MARKET_CONTEXT", [])

        opportunities, market_context = get_buy_opportunities_with_context(
            max_markets=2
        )

        self.assertEqual(opportunities, ["BUY_TEST"])
        self.assertEqual(market_context, "MARKET_CONTEXT")
        mock_analyze_market.assert_called_once()
        fake_client.close.assert_called_once()
    @mock.patch("wallex_assistant.buy_opportunity.BuyOpportunityScanner")
    @mock.patch("wallex_assistant.portfolio.MarketClient.from_settings")
    def test_closes_client_when_history_request_fails(
        self,
        mock_from_settings,
        mock_scanner_class,
    ) -> None:
        fake_client = mock.Mock()
        mock_from_settings.return_value = fake_client

        fake_client.get_market_stats.return_value = [
            MarketStat(
                symbol="BTCTMN",
                quote_volume_24h=Decimal("1000"),
            ),
        ]
        fake_client.get_history.side_effect = RuntimeError("API unavailable")

        scanner = mock_scanner_class.return_value
        scanner.scan.return_value = []

        result = get_buy_opportunities()

        self.assertEqual(result, [])
        scanner.scan.assert_called_once_with(["BTCTMN"], {})
        fake_client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)

