"""Offline tests for deterministic technical and decision analysis."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from wallex_assistant.analysis import ScoringWeights, analyze_market, calculate_indicators
from wallex_assistant.market_client import Candle


def candles(count=260, trend=1):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = 100.0
    for i in range(count):
        price += trend * (0.25 if i % 4 else 0.1)
        rows.append(Candle(start + timedelta(days=i), Decimal(str(price - .1)), Decimal(str(price + 1)), Decimal(str(price - 1)), Decimal(str(price)), Decimal(str(100 + i % 9))))
    return rows


class TestAnalysis(unittest.TestCase):
    def test_indicators_are_computed_and_timestamped(self):
        result = calculate_indicators(candles())
        self.assertEqual(result["candles"], 260)
        self.assertIsNotNone(result["rsi_14"])
        self.assertIsNotNone(result["ema_200"])
        self.assertIsNotNone(result["adx_14"])
        self.assertTrue(result["data_as_of"].startswith("2024-"))

    def test_insufficient_data_never_produces_signal_or_score(self):
        _, results = analyze_market({"TEST": {"1d": candles(30), "1h": candles(30)}})
        self.assertIsNone(results[0].signal)
        self.assertIsNone(results[0].score)

    def test_multi_timeframe_correction_waits_for_entry(self):
        _, results = analyze_market({"TEST": {"1d": candles(260, 1), "1h": candles(260, -1)}})
        self.assertEqual(results[0].signal, "WAIT FOR ENTRY")

    def test_weights_validate_and_normalize(self):
        weights = ScoringWeights(trend=2, momentum=0)
        self.assertAlmostEqual(sum(weights.as_dict().values()), 1)
        with self.assertRaises(ValueError):
            ScoringWeights(trend=0, momentum=0, volume=0, volatility=0, timeframe_agreement=0, risk_reward=0, market=0)

    def test_missing_volume_remains_missing(self):
        data = calculate_indicators([Candle(row.open_time, row.open, row.high, row.low, row.close, None) for row in candles()])
        self.assertIsNone(data["volume"])
        self.assertIsNone(data["volume_vs_20_period"])


if __name__ == "__main__":
    unittest.main()
