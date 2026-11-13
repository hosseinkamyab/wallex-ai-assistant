"""Tests for the read-only account client.

The guarded HTTP client is faked, so nothing here touches the network.
"""

from __future__ import annotations

import unittest
from datetime import timezone
from decimal import Decimal
from unittest import mock

from wallex_assistant.account_client import (
    AccountClient,
    Balance,
    _parse_timestamp,
    _to_decimal_safe,
)
from wallex_assistant.config import ConfigError, Settings
from wallex_assistant.errors import ReadOnlyViolation, WallexResponseError


def _client_with(payload) -> AccountClient:
    guarded = mock.Mock()
    guarded.get.return_value = payload
    return AccountClient(guarded)


class TestDecimalHelper(unittest.TestCase):
    def test_parses_string_and_number(self) -> None:
        self.assertEqual(_to_decimal_safe("1.5"), Decimal("1.5"))
        self.assertEqual(_to_decimal_safe(2), Decimal("2"))

    def test_junk_returns_none_instead_of_raising(self) -> None:
        # A single odd balance must not take down the whole portfolio view.
        self.assertIsNone(_to_decimal_safe("n/a"))
        self.assertIsNone(_to_decimal_safe(None))
        self.assertIsNone(_to_decimal_safe(""))


class TestBalanceModel(unittest.TestCase):
    def test_total_is_available_plus_locked(self) -> None:
        bal = Balance(asset="BTC", available=Decimal("1"), locked=Decimal("0.5"))
        self.assertEqual(bal.total, Decimal("1.5"))

    def test_is_empty_when_total_is_zero(self) -> None:
        self.assertTrue(Balance(asset="X").is_empty)

    def test_from_api_with_available_and_locked(self) -> None:
        bal = Balance.from_api(
            "BTC", {"available": "1.25", "locked": "0.75"}
        )
        self.assertEqual(bal.available, Decimal("1.25"))
        self.assertEqual(bal.locked, Decimal("0.75"))
        self.assertEqual(bal.total, Decimal("2"))

    def test_from_api_accepts_balance_key(self) -> None:
        bal = Balance.from_api("ETH", {"balance": "3"})
        self.assertEqual(bal.available, Decimal("3"))

    def test_total_only_response_becomes_available(self) -> None:
        # A response that reports only a total must not be lost.
        bal = Balance.from_api("DOGE", {"total": "500"})
        self.assertEqual(bal.available, Decimal("500"))
        self.assertEqual(bal.total, Decimal("500"))

    def test_missing_fields_default_to_zero(self) -> None:
        bal = Balance.from_api("X", {})
        self.assertEqual(bal.total, Decimal("0"))

    def test_as_dict_uses_strings(self) -> None:
        bal = Balance(asset="BTC", available=Decimal("1"))
        self.assertEqual(bal.as_dict()["available"], "1")


class TestBalancesEndpoint(unittest.TestCase):
    def test_parses_mapping_shape(self) -> None:
        client = _client_with(
            {
                "balances": {
                    "BTC": {"available": "1", "locked": "0"},
                    "TMN": {"available": "500000", "locked": "0"},
                }
            }
        )
        balances = client.get_balances()
        self.assertEqual({b.asset for b in balances}, {"BTC", "TMN"})

    def test_parses_list_shape(self) -> None:
        client = _client_with(
            {"balances": [{"asset": "BTC", "available": "2"}]}
        )
        balances = client.get_balances()
        self.assertEqual(balances[0].asset, "BTC")

    def test_empty_balances_are_filtered_out(self) -> None:
        # Dust clutters the dashboard and carries no value.
        client = _client_with(
            {
                "balances": {
                    "BTC": {"available": "1"},
                    "DUST": {"available": "0", "locked": "0"},
                }
            }
        )
        assets = [b.asset for b in client.get_balances()]
        self.assertEqual(assets, ["BTC"])

    def test_bare_number_entries_are_understood(self) -> None:
        client = _client_with({"balances": {"BTC": "0.5"}})
        self.assertEqual(client.get_balances()[0].available, Decimal("0.5"))

    def test_wrong_shape_raises_response_error(self) -> None:
        client = _client_with({"balances": 42})
        with self.assertRaises(WallexResponseError):
            client.get_balances()

    def test_results_are_sorted_by_asset(self) -> None:
        client = _client_with(
            {"balances": {"ZZZ": {"available": "1"}, "AAA": {"available": "1"}}}
        )
        self.assertEqual(
            [b.asset for b in client.get_balances()], ["AAA", "ZZZ"]
        )


class TestOrdersEndpoint(unittest.TestCase):
    def test_parses_open_orders(self) -> None:
        client = _client_with(
            {
                "orders": [
                    {
                        "id": "abc",
                        "symbol": "BTCTMN",
                        "side": "buy",
                        "price": "1000",
                        "quantity": "0.1",
                    }
                ]
            }
        )
        order = client.get_open_orders()[0]
        self.assertEqual(order.order_id, "abc")
        self.assertEqual(order.side, "buy")
        self.assertEqual(order.price, Decimal("1000"))

    def test_empty_result(self) -> None:
        self.assertEqual(_client_with({"orders": []}).get_open_orders(), [])

    def test_wrong_shape_raises(self) -> None:
        with self.assertRaises(WallexResponseError):
            _client_with({"orders": "nope"}).get_open_orders()

    def test_missing_id_is_tolerated(self) -> None:
        client = _client_with({"orders": [{"symbol": "BTCTMN"}]})
        self.assertEqual(client.get_open_orders()[0].order_id, "unknown")


class TestFillsEndpoint(unittest.TestCase):
    def test_parses_fills(self) -> None:
        client = _client_with(
            {
                "fills": [
                    {
                        "id": "f1",
                        "symbol": "BTCTMN",
                        "price": "900",
                        "quantity": "0.01",
                        "fee": "0.5",
                        "feeAsset": "TMN",
                    }
                ]
            }
        )
        fill = client.get_fills()[0]
        self.assertEqual(fill.fill_id, "f1")
        self.assertEqual(fill.fee_asset, "TMN")

    def test_wrong_shape_raises(self) -> None:
        with self.assertRaises(WallexResponseError):
            _client_with({"fills": 7}).get_fills()


class TestTimestampParsing(unittest.TestCase):
    def test_epoch_seconds(self) -> None:
        dt = _parse_timestamp(1700000000)
        self.assertEqual(dt.year, 2023)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_epoch_milliseconds(self) -> None:
        # Values this large are milliseconds, not seconds.
        dt = _parse_timestamp(1700000000000)
        self.assertEqual(dt.year, 2023)

    def test_iso_string(self) -> None:
        dt = _parse_timestamp("2024-05-01T10:30:00Z")
        self.assertEqual(dt.year, 2024)
        self.assertEqual(dt.hour, 10)

    def test_numeric_string(self) -> None:
        self.assertIsNotNone(_parse_timestamp("1700000000"))

    def test_invalid_returns_none(self) -> None:
        self.assertIsNone(_parse_timestamp("not a date"))
        self.assertIsNone(_parse_timestamp(None))


class TestCredentialRequirements(unittest.TestCase):
    def test_missing_key_raises_config_error(self) -> None:
        with self.assertRaises(ConfigError):
            AccountClient.from_settings(Settings(wallex_api_key=""))

    def test_key_is_passed_to_the_http_layer(self) -> None:
        with mock.patch("wallex_assistant.account_client.WallexHttpClient") as h:
            AccountClient.from_settings(Settings(wallex_api_key="k-123456789"))
        h.assert_called_once()
        self.assertEqual(h.call_args.kwargs["api_key"], "k-123456789")

    def test_constructed_around_a_guarded_client(self) -> None:
        # The client must be wrapped in ReadOnlyClient, not left bare.
        with mock.patch("wallex_assistant.account_client.WallexHttpClient"):
            client = AccountClient.from_settings(
                Settings(wallex_api_key="k-123456789")
            )
        from wallex_assistant.readonly import ReadOnlyClient

        self.assertIsInstance(client._client, ReadOnlyClient)  # noqa: SLF001


class TestReadOnlyEnforcement(unittest.TestCase):
    def test_blocked_path_raises_through_the_client(self) -> None:
        # A real guarded client around a fake transport: the guard must fire.
        from wallex_assistant.readonly import ReadOnlyClient as Guard

        inner = mock.Mock()
        client = AccountClient(Guard(inner))
        with self.assertRaises(ReadOnlyViolation):
            client._client.get("/v1/account/withdraw")  # noqa: SLF001
        inner.get.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
