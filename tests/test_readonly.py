"""Tests for the read-only guard.

These are the most important tests in the project: they are what makes
"this application cannot trade" a verified fact rather than a claim.
"""

from __future__ import annotations

import unittest
from unittest import mock

from wallex_assistant.errors import ReadOnlyViolation
from wallex_assistant.readonly import (
    ALLOWED_PATHS,
    ReadOnlyClient,
    assert_read_only,
    is_allowed,
)


class TestAllowedPaths(unittest.TestCase):
    def test_known_read_endpoints_are_allowed(self) -> None:
        for path in sorted(ALLOWED_PATHS):
            with self.subTest(path=path):
                self.assertIsNone(assert_read_only(path))

    def test_market_endpoints_are_allowed(self) -> None:
        for path in ("/v1/markets", "/v1/market-status", "/v1/depth"):
            with self.subTest(path=path):
                assert_read_only(path)

    def test_account_read_endpoints_are_allowed(self) -> None:
        for path in (
            "/v1/account/balances",
            "/v1/account/openOrders",
            "/v1/account/fills",
        ):
            with self.subTest(path=path):
                assert_read_only(path)

    def test_unknown_path_is_blocked(self) -> None:
        with self.assertRaises(ReadOnlyViolation):
            assert_read_only("/v1/some/new/endpoint")

    def test_trailing_slash_is_tolerated_for_allowed_path(self) -> None:
        assert_read_only("/v1/markets/")


class TestWriteMethodsBlocked(unittest.TestCase):
    def test_post_is_blocked(self) -> None:
        with self.assertRaises(ReadOnlyViolation) as ctx:
            assert_read_only("/v1/markets", method="POST")
        self.assertIn("POST", str(ctx.exception))

    def test_put_patch_and_delete_are_blocked(self) -> None:
        for method in ("PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                with self.assertRaises(ReadOnlyViolation):
                    assert_read_only("/v1/markets", method=method)

    def test_post_to_an_allowed_path_is_still_blocked(self) -> None:
        # The path being harmless does not make the method harmless.
        with self.assertRaises(ReadOnlyViolation):
            assert_read_only("/v1/account/balances", method="POST")

    def test_method_check_is_case_insensitive(self) -> None:
        with self.assertRaises(ReadOnlyViolation):
            assert_read_only("/v1/markets", method="post")


class TestDangerousPathFragments(unittest.TestCase):
    """Even an allowlisted-shaped path must fail if it smells like a write."""

    def test_withdraw_is_blocked(self) -> None:
        with self.assertRaises(ReadOnlyViolation) as ctx:
            assert_read_only("/v1/account/withdraw")
        self.assertIn("withdraw", str(ctx.exception).lower())

    def test_transfer_is_blocked(self) -> None:
        with self.assertRaises(ReadOnlyViolation):
            assert_read_only("/v1/account/transfer")

    def test_order_creation_path_is_blocked(self) -> None:
        with self.assertRaises(ReadOnlyViolation):
            assert_read_only("/v1/account/order/create")

    def test_cancel_is_blocked(self) -> None:
        with self.assertRaises(ReadOnlyViolation):
            assert_read_only("/v1/account/order/cancel")

    def test_trade_endpoint_is_blocked(self) -> None:
        with self.assertRaises(ReadOnlyViolation):
            assert_read_only("/v1/trade/execute")

    def test_fragment_check_is_case_insensitive(self) -> None:
        with self.assertRaises(ReadOnlyViolation):
            assert_read_only("/v1/account/WITHDRAW")


class TestInvalidPaths(unittest.TestCase):
    def test_empty_path_is_blocked(self) -> None:
        with self.assertRaises(ReadOnlyViolation):
            assert_read_only("")

    def test_none_path_is_blocked(self) -> None:
        with self.assertRaises(ReadOnlyViolation):
            assert_read_only(None)  # type: ignore[arg-type]


class TestIsAllowed(unittest.TestCase):
    def test_returns_true_for_permitted_path(self) -> None:
        self.assertTrue(is_allowed("/v1/markets"))

    def test_returns_false_instead_of_raising(self) -> None:
        self.assertFalse(is_allowed("/v1/account/withdraw"))
        self.assertFalse(is_allowed("/v1/nonsense"))


class TestReadOnlyClientWrapper(unittest.TestCase):
    def setUp(self) -> None:
        self.inner = mock.Mock()
        self.inner.get.return_value = {"ok": True}
        self.client = ReadOnlyClient(self.inner)

    def test_allowed_get_is_forwarded(self) -> None:
        self.assertEqual(self.client.get("/v1/markets"), {"ok": True})
        self.inner.get.assert_called_once()

    def test_params_are_forwarded(self) -> None:
        self.client.get("/v1/depth", params={"symbol": "BTCTMN"})
        self.inner.get.assert_called_once_with(
            "/v1/depth", params={"symbol": "BTCTMN"}
        )

    def test_blocked_path_never_reaches_the_inner_client(self) -> None:
        # This is the key property: a rejected call must not be forwarded at
        # all, so nothing can leave the machine.
        with self.assertRaises(ReadOnlyViolation):
            self.client.get("/v1/account/withdraw")
        self.inner.get.assert_not_called()

    def test_close_is_forwarded(self) -> None:
        self.client.close()
        self.inner.close.assert_called_once()

    def test_context_manager_closes(self) -> None:
        with ReadOnlyClient(self.inner):
            pass
        self.inner.close.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
