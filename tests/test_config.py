"""Tests for configuration loading, validation and secret masking.

Run from the project root:

    .venv/Scripts/python.exe -m unittest discover -s tests -v

These tests never read your real `.env`: they point `Settings.load()` at a
path that does not exist and control the environment explicitly. That keeps
them fast, offline and independent of your machine's setup.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from wallex_assistant.config import (
    ConfigError,
    Settings,
    get_settings,
    mask_secret,
)

# A path that we fully control and that certainly does not exist.
_ABSENT_ENV = Path("__does_not_exist__.env")

# Environment variables this module cares about -- cleared before each test.
_MANAGED_VARS = (
    "WALLEX_API_KEY",
    "WALLEX_BASE_URL",
    "LOG_LEVEL",
    "APP_LANGUAGE",
    "REQUEST_TIMEOUT",
    "MAX_RETRIES",
    "LLM_PROVIDER",
    "LLM_API_KEY",
)


class CleanEnvTestCase(unittest.TestCase):
    """Base class that guarantees a predictable environment."""

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in _MANAGED_VARS:
            os.environ.pop(name, None)

    def load(self, env_file: Path = _ABSENT_ENV) -> Settings:
        return Settings.load(env_file=env_file)


class TestMaskSecret(unittest.TestCase):
    def test_long_secret_shows_only_last_four(self) -> None:
        self.assertEqual(mask_secret("sk-ant-abcdefgh1234"), "****1234")

    def test_short_secret_is_fully_hidden(self) -> None:
        # Showing part of a short secret would leak too much of it.
        self.assertEqual(mask_secret("abc123"), "****")

    def test_empty_and_none_report_not_set(self) -> None:
        self.assertEqual(mask_secret(""), "<not set>")
        self.assertEqual(mask_secret(None), "<not set>")

    def test_never_returns_the_original_value(self) -> None:
        secret = "SUPER-SECRET-VALUE-9876"
        masked = mask_secret(secret)
        self.assertNotIn("SUPER", masked)
        self.assertNotIn(secret, masked)


class TestSettingsDefaults(CleanEnvTestCase):
    def test_defaults_when_nothing_is_set(self) -> None:
        settings = self.load()
        self.assertEqual(settings.wallex_api_key, "")
        self.assertEqual(settings.wallex_base_url, "https://api.wallex.ir")
        self.assertEqual(settings.log_level, "INFO")
        self.assertEqual(settings.language, "en")
        self.assertEqual(settings.request_timeout, 15)
        self.assertEqual(settings.max_retries, 3)
        self.assertEqual(settings.llm_provider, "mock")

    def test_public_data_works_without_a_key(self) -> None:
        # No key must NOT be an error: market data is public.
        settings = self.load()
        self.assertFalse(settings.has_wallex_key)
        settings.validate()  # must not raise

    def test_api_key_required_only_when_requested(self) -> None:
        settings = self.load()
        with self.assertRaises(ConfigError) as ctx:
            settings.validate(require_api_key=True)
        self.assertIn("WALLEX_API_KEY", str(ctx.exception))


class TestSettingsFromEnvironment(CleanEnvTestCase):
    def test_reads_values_from_environment(self) -> None:
        os.environ["WALLEX_API_KEY"] = "my-key-123456"
        os.environ["LOG_LEVEL"] = "debug"          # should be upper-cased
        os.environ["APP_LANGUAGE"] = "FA"          # should be lower-cased
        os.environ["REQUEST_TIMEOUT"] = "30"

        settings = self.load()
        self.assertEqual(settings.wallex_api_key, "my-key-123456")
        self.assertEqual(settings.log_level, "DEBUG")
        self.assertEqual(settings.language, "fa")
        self.assertEqual(settings.request_timeout, 30)

    def test_trailing_slash_is_stripped_from_base_url(self) -> None:
        os.environ["WALLEX_BASE_URL"] = "https://api.wallex.ir/"
        self.assertEqual(
            self.load().wallex_base_url, "https://api.wallex.ir"
        )

    def test_bad_number_falls_back_to_default(self) -> None:
        os.environ["REQUEST_TIMEOUT"] = "fifteen"
        self.assertEqual(self.load().request_timeout, 15)

    def test_zero_or_negative_timeout_falls_back(self) -> None:
        os.environ["REQUEST_TIMEOUT"] = "0"
        self.assertEqual(self.load().request_timeout, 15)

    def test_zero_retries_is_allowed(self) -> None:
        # MAX_RETRIES=0 legitimately means "do not retry".
        os.environ["MAX_RETRIES"] = "0"
        self.assertEqual(self.load().max_retries, 0)


class TestValidation(CleanEnvTestCase):
    def test_invalid_log_level_is_rejected(self) -> None:
        os.environ["LOG_LEVEL"] = "LOUD"
        with self.assertRaises(ConfigError) as ctx:
            self.load().validate()
        self.assertIn("LOG_LEVEL", str(ctx.exception))

    def test_invalid_language_is_rejected(self) -> None:
        os.environ["APP_LANGUAGE"] = "klingon"
        with self.assertRaises(ConfigError) as ctx:
            self.load().validate()
        self.assertIn("APP_LANGUAGE", str(ctx.exception))

    def test_base_url_without_scheme_is_rejected(self) -> None:
        os.environ["WALLEX_BASE_URL"] = "api.wallex.ir"
        with self.assertRaises(ConfigError) as ctx:
            self.load().validate()
        self.assertIn("WALLEX_BASE_URL", str(ctx.exception))

    def test_multiple_problems_are_reported_together(self) -> None:
        os.environ["LOG_LEVEL"] = "LOUD"
        os.environ["APP_LANGUAGE"] = "klingon"
        with self.assertRaises(ConfigError) as ctx:
            self.load().validate()
        message = str(ctx.exception)
        self.assertIn("LOG_LEVEL", message)
        self.assertIn("APP_LANGUAGE", message)


class TestDotEnvFile(CleanEnvTestCase):
    def test_values_are_read_from_env_file(self) -> None:
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "WALLEX_API_KEY=from-the-file-9999\n"
                "LOG_LEVEL=WARNING\n",
                encoding="utf-8",
            )
            settings = Settings.load(env_file=env_file)

        self.assertEqual(settings.wallex_api_key, "from-the-file-9999")
        self.assertEqual(settings.log_level, "WARNING")

    def test_real_environment_wins_over_env_file(self) -> None:
        # A variable already set in the environment must not be overwritten.
        os.environ["LOG_LEVEL"] = "ERROR"
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("LOG_LEVEL=WARNING\n", encoding="utf-8")
            settings = Settings.load(env_file=env_file)

        self.assertEqual(settings.log_level, "ERROR")

    def test_missing_env_file_is_not_an_error(self) -> None:
        settings = Settings.load(env_file=Path("__nope__.env"))
        self.assertEqual(settings.log_level, "INFO")


class TestSecretLeakage(CleanEnvTestCase):
    """The single most important group: secrets must not escape."""

    def test_describe_does_not_contain_the_key(self) -> None:
        os.environ["WALLEX_API_KEY"] = "sk-wallex-SECRETVALUE-4455"
        os.environ["LLM_API_KEY"] = "sk-llm-SECRETVALUE-7788"
        text = self.load().describe()

        self.assertNotIn("SECRETVALUE", text)
        self.assertIn("4455", text)  # last 4 characters are fine
        self.assertIn("7788", text)

    def test_repr_does_not_contain_the_key(self) -> None:
        os.environ["WALLEX_API_KEY"] = "sk-wallex-SECRETVALUE-4455"
        text = repr(self.load())
        self.assertNotIn("SECRETVALUE", text)

    def test_describe_reports_whether_env_file_was_found(self) -> None:
        self.assertIn(".env file", self.load().describe())


class TestGetSettings(CleanEnvTestCase):
    def test_get_settings_returns_a_valid_settings_object(self) -> None:
        # get_settings() reads the real .env path; with a clean environment and
        # valid defaults that must still succeed.
        with mock.patch(
            "wallex_assistant.config.Settings.load",
            return_value=Settings(),
        ):
            settings = get_settings()
        self.assertIsInstance(settings, Settings)


if __name__ == "__main__":
    unittest.main(verbosity=2)
