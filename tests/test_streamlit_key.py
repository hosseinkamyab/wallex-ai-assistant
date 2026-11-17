from __future__ import annotations

import unittest
from unittest.mock import patch

from streamlit_app import build_runtime_settings, validate_wallex_api_key
from wallex_assistant.config import Settings
from wallex_assistant.errors import WallexAuthError


class FakeHttpClient:
    def __init__(self, *, failure=None, **kwargs):
        self.failure = failure
        self.closed = False
        self.requested = []

    def get(self, path):
        self.requested.append(path)
        if self.failure:
            raise self.failure
        return {}

    def close(self):
        self.closed = True


class TestInAppAPIKey(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            wallex_api_key="environment-key",
            wallex_base_url="https://api.wallex.ir",
            log_level="WARNING",
            language="fa",
            request_timeout=9,
            max_retries=1,
            llm_provider="mock",
            llm_api_key="llm-key",
        )

    def test_runtime_settings_use_trimmed_session_key_and_preserve_other_settings(self):
        runtime = build_runtime_settings(self.settings, "  session-key  ")
        self.assertEqual(runtime.wallex_api_key, "session-key")
        self.assertEqual(runtime.wallex_base_url, self.settings.wallex_base_url)
        self.assertEqual(runtime.request_timeout, self.settings.request_timeout)
        self.assertEqual(runtime.language, self.settings.language)
        self.assertEqual(runtime.llm_api_key, self.settings.llm_api_key)

    def test_empty_session_key_preserves_base_settings(self):
        self.assertIs(build_runtime_settings(self.settings, "  "), self.settings)

    def test_validation_is_read_only_and_closes_client(self):
        fake = FakeHttpClient()
        with patch("streamlit_app.WallexHttpClient", return_value=fake) as factory:
            ok, message = validate_wallex_api_key(
                "session-key",
                base_url="https://api.wallex.ir",
                timeout=10,
                max_retries=2,
            )
        self.assertTrue(ok)
        self.assertIn("Connected", message)
        self.assertEqual(fake.requested, ["/v1/account/balances"])
        self.assertTrue(fake.closed)
        self.assertEqual(factory.call_args.kwargs["api_key"], "session-key")

    def test_validation_does_not_expose_auth_error_content_and_closes_client(self):
        secret = "do-not-display-this-key"
        fake = FakeHttpClient(failure=WallexAuthError(secret, status_code=401))
        with patch("streamlit_app.WallexHttpClient", return_value=fake):
            ok, message = validate_wallex_api_key(
                secret,
                base_url="https://api.wallex.ir",
                timeout=10,
                max_retries=2,
            )
        self.assertFalse(ok)
        self.assertNotIn(secret, message)
        self.assertTrue(fake.closed)

    def test_blank_key_does_not_make_http_client(self):
        with patch("streamlit_app.WallexHttpClient") as factory:
            ok, _ = validate_wallex_api_key(
                "  ",
                base_url="https://api.wallex.ir",
                timeout=10,
                max_retries=2,
            )
        self.assertFalse(ok)
        factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
