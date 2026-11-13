"""Tests for the HTTP transport layer.

No network access: `requests.Session.get` is replaced with a fake, so these
tests are fast, deterministic, and safe to run offline.
"""

from __future__ import annotations

import unittest
from unittest import mock

import requests

from wallex_assistant.errors import (
    WallexAPIError,
    WallexAuthError,
    WallexNetworkError,
    WallexNotFoundError,
    WallexRateLimitError,
    WallexResponseError,
)
from wallex_assistant.http import WallexHttpClient


def _response(status: int, body, headers: dict | None = None) -> mock.Mock:
    """Build a fake `requests.Response`."""
    resp = mock.Mock(spec=requests.Response)
    resp.status_code = status
    resp.headers = headers or {}
    if isinstance(body, (dict, list)):
        resp.json.return_value = body
        resp.text = str(body)
    else:
        resp.json.side_effect = ValueError("not json")
        resp.text = str(body)
    return resp


class HttpClientTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # No real sleeping during retry tests.
        sleep_patcher = mock.patch("wallex_assistant.http.time.sleep")
        self.sleep = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def make_client(self, **kwargs) -> WallexHttpClient:
        client = WallexHttpClient("https://api.wallex.ir", **kwargs)
        self.addCleanup(client.close)
        # Stop jitter from making backoff assertions non-deterministic.
        client._backoff_delay = lambda attempt: 0.0  # noqa: SLF001
        return client


class TestSuccessPaths(HttpClientTestCase):
    def test_unwraps_result_envelope(self) -> None:
        client = self.make_client()
        resp = _response(200, {"success": True, "result": {"symbols": {}}})
        with mock.patch.object(client._session, "get", return_value=resp):
            self.assertEqual(client.get("/v1/markets"), {"symbols": {}})

    def test_returns_body_when_there_is_no_envelope(self) -> None:
        client = self.make_client()
        resp = _response(200, {"s": "ok", "t": [1, 2]})
        with mock.patch.object(client._session, "get", return_value=resp):
            self.assertEqual(client.get("/v1/udf/history"), {"s": "ok", "t": [1, 2]})

    def test_path_gets_a_leading_slash(self) -> None:
        client = self.make_client()
        resp = _response(200, {"result": {}})
        with mock.patch.object(client._session, "get", return_value=resp) as get:
            client.get("v1/markets")
        self.assertEqual(get.call_args[0][0], "https://api.wallex.ir/v1/markets")

    def test_timeout_is_always_passed(self) -> None:
        # A request without a timeout can hang forever.
        client = self.make_client(timeout=7)
        resp = _response(200, {"result": {}})
        with mock.patch.object(client._session, "get", return_value=resp) as get:
            client.get("/v1/markets")
        self.assertEqual(get.call_args.kwargs["timeout"], 7)


class TestErrorMapping(HttpClientTestCase):
    def _raise_for(self, status: int, body=None, headers=None):
        client = self.make_client()
        resp = _response(status, body or {"message": "boom"}, headers)
        with mock.patch.object(client._session, "get", return_value=resp):
            client.get("/v1/test")

    def test_401_is_auth_error(self) -> None:
        with self.assertRaises(WallexAuthError):
            self._raise_for(401)

    def test_403_is_auth_error(self) -> None:
        with self.assertRaises(WallexAuthError):
            self._raise_for(403)

    def test_404_is_not_found(self) -> None:
        with self.assertRaises(WallexNotFoundError):
            self._raise_for(404)

    def test_429_is_rate_limit(self) -> None:
        with self.assertRaises(WallexRateLimitError):
            self._raise_for(429)

    def test_500_is_generic_api_error(self) -> None:
        with self.assertRaises(WallexAPIError) as ctx:
            self._raise_for(500)
        self.assertNotIsInstance(ctx.exception, (WallexAuthError,))

    def test_success_false_is_an_error(self) -> None:
        with self.assertRaises(WallexAPIError) as ctx:
            self._raise_for(200, {"success": False, "message": "bad symbol"})
        self.assertIn("bad symbol", str(ctx.exception))

    def test_error_message_is_extracted_from_body(self) -> None:
        with self.assertRaises(WallexAPIError) as ctx:
            self._raise_for(400, {"error": "invalid symbol"})
        self.assertIn("invalid symbol", str(ctx.exception))

    def test_auth_error_hints_when_no_key_present(self) -> None:
        with self.assertRaises(WallexAuthError) as ctx:
            self._raise_for(401)
        self.assertIn("no API key", str(ctx.exception))

    def test_non_json_response_is_response_error(self) -> None:
        with self.assertRaises(WallexResponseError):
            self._raise_for(200, "<html>not json</html>")

    def test_json_array_is_response_error(self) -> None:
        # We expect an object, not a bare list.
        with self.assertRaises(WallexResponseError):
            self._raise_for(200, [1, 2, 3])


class TestRetries(HttpClientTestCase):
    def test_network_error_is_retried_then_raises(self) -> None:
        client = self.make_client(max_retries=2)
        with mock.patch.object(
            client._session, "get",
            side_effect=requests.ConnectionError("no route"),
        ) as get:
            with self.assertRaises(WallexNetworkError):
                client.get("/v1/markets")
        # 1 initial attempt + 2 retries
        self.assertEqual(get.call_count, 3)

    def test_retry_then_success(self) -> None:
        client = self.make_client(max_retries=2)
        ok = _response(200, {"result": {"ok": True}})
        with mock.patch.object(
            client._session, "get",
            side_effect=[requests.ConnectionError("blip"), ok],
        ):
            self.assertEqual(client.get("/v1/markets"), {"ok": True})

    def test_auth_error_is_not_retried(self) -> None:
        # Retrying a bad key wastes time and can trigger rate limiting.
        client = self.make_client(max_retries=3)
        resp = _response(401, {"message": "unauthorized"})
        with mock.patch.object(
            client._session, "get", return_value=resp
        ) as get:
            with self.assertRaises(WallexAuthError):
                client.get("/v1/account/balances")
        self.assertEqual(get.call_count, 1)

    def test_not_found_is_not_retried(self) -> None:
        client = self.make_client(max_retries=3)
        resp = _response(404, {"message": "nope"})
        with mock.patch.object(
            client._session, "get", return_value=resp
        ) as get:
            with self.assertRaises(WallexNotFoundError):
                client.get("/v1/nothing")
        self.assertEqual(get.call_count, 1)

    def test_rate_limit_honours_retry_after(self) -> None:
        client = self.make_client(max_retries=1)
        limited = _response(429, {"message": "slow down"},
                            headers={"Retry-After": "5"})
        ok = _response(200, {"result": {"ok": True}})
        with mock.patch.object(
            client._session, "get", side_effect=[limited, ok]
        ):
            result = client.get("/v1/markets")

        self.assertEqual(result, {"ok": True})
        # The server asked for 5s, so we should have slept exactly that.
        self.sleep.assert_any_call(5.0)

    def test_absurd_retry_after_is_ignored(self) -> None:
        client = self.make_client(max_retries=1)
        limited = _response(429, {"message": "x"},
                            headers={"Retry-After": "99999"})
        ok = _response(200, {"result": {}})
        with mock.patch.object(
            client._session, "get", side_effect=[limited, ok]
        ):
            client.get("/v1/markets")
        # Must not sleep for the nonsense value.
        self.assertNotIn(99999.0, [c.args[0] for c in self.sleep.call_args_list])

    def test_zero_retries_means_one_attempt(self) -> None:
        client = self.make_client(max_retries=0)
        with mock.patch.object(
            client._session, "get",
            side_effect=requests.Timeout("slow"),
        ) as get:
            with self.assertRaises(WallexNetworkError):
                client.get("/v1/markets")
        self.assertEqual(get.call_count, 1)


class TestCredentialHandling(unittest.TestCase):
    def test_key_is_sent_as_header_not_in_url(self) -> None:
        client = WallexHttpClient("https://api.wallex.ir", api_key="secret-key")
        self.addCleanup(client.close)
        self.assertEqual(
            client._session.headers["x-api-key"], "secret-key"  # noqa: SLF001
        )
        self.assertNotIn("secret-key", client.base_url)

    def test_no_key_means_no_header(self) -> None:
        client = WallexHttpClient("https://api.wallex.ir")
        self.addCleanup(client.close)
        self.assertNotIn("x-api-key", client._session.headers)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main(verbosity=2)
