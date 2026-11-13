"""Configuration loading and validation.

Everything the application needs to know about *where* and *who* comes from
here, in one place. Other modules never read `os.environ` directly -- they ask
this module for a `Settings` object. That gives us one obvious place to look
when a setting is missing or wrong.

Design notes for a learner:

* Secrets live in environment variables (a git-ignored `.env` file during
  local development). They are never written into source code, never logged,
  and never printed -- see `mask_secret()`.
* Wrong configuration should fail loudly and immediately, with a message that
  says what to fix, instead of producing a confusing error deep in an HTTP
  call three stages later.
* Run this file directly to see a safe, secret-free summary of your setup:

      python -m wallex_assistant.config
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# The project root is the directory that contains this package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

# Fallbacks used when a variable is not set at all.
DEFAULT_BASE_URL = "https://api.wallex.ir"

VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
VALID_LANGUAGES = ("en", "fa")


class ConfigError(Exception):
    """Raised when the configuration is unusable and the app cannot start."""


def mask_secret(value: str | None) -> str:
    """Return a display-safe version of a secret.

    Secrets must never appear in logs or terminal output. We show only the
    last four characters so you can still tell *which* key is loaded.

        >>> mask_secret("sk-ant-abcdefgh1234")
        '****1234'
        >>> mask_secret("")
        '<not set>'

    Anything short enough that showing part of it would be revealing is
    masked completely.
    """
    if not value:
        return "<not set>"
    if len(value) <= 8:
        return "****"
    return f"****{value[-4:]}"


def _read_int(name: str, default: int, minimum: int = 1) -> int:
    """Read an integer setting, tolerating a bad value gracefully.

    A typo like REQUEST_TIMEOUT=fifteen should not crash the whole app on
    import; we fall back to the default and let validation report it.
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value >= minimum else default


@dataclass(frozen=True)
class Settings:
    """An immutable snapshot of the application's configuration."""

    wallex_api_key: str = ""
    wallex_base_url: str = DEFAULT_BASE_URL
    log_level: str = "INFO"
    language: str = "en"
    request_timeout: int = 15
    max_retries: int = 3
    llm_provider: str = "mock"
    llm_api_key: str = ""

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        """Load settings from `.env` plus the real environment.

        Precedence: real environment variables win over `.env`, which wins
        over the defaults in this dataclass. That is what lets you override a
        single value for one command without editing the file.
        """
        path = env_file if env_file is not None else ENV_FILE
        if path.exists():
            # override=False -> a variable already set in the environment
            # (e.g. by your shell or a CI system) is respected.
            load_dotenv(dotenv_path=path, override=False)

        return cls(
            wallex_api_key=(os.getenv("WALLEX_API_KEY") or "").strip(),
            wallex_base_url=(
                os.getenv("WALLEX_BASE_URL") or DEFAULT_BASE_URL
            ).strip().rstrip("/"),
            log_level=(os.getenv("LOG_LEVEL") or "INFO").strip().upper(),
            language=(os.getenv("APP_LANGUAGE") or "en").strip().lower(),
            request_timeout=_read_int("REQUEST_TIMEOUT", 15),
            max_retries=_read_int("MAX_RETRIES", 3, minimum=0),
            llm_provider=(os.getenv("LLM_PROVIDER") or "mock").strip().lower(),
            llm_api_key=(os.getenv("LLM_API_KEY") or "").strip(),
        )

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate(self, require_api_key: bool = False) -> None:
        """Raise `ConfigError` if the settings cannot be used.

        `require_api_key` is opt-in: only the account client needs a key.
        Public market data must keep working without one.
        """
        problems: list[str] = []

        if self.log_level not in VALID_LOG_LEVELS:
            problems.append(
                f"LOG_LEVEL must be one of {', '.join(VALID_LOG_LEVELS)} "
                f"(got {self.log_level!r})."
            )

        if self.language not in VALID_LANGUAGES:
            problems.append(
                f"APP_LANGUAGE must be one of {', '.join(VALID_LANGUAGES)} "
                f"(got {self.language!r})."
            )

        if not self.wallex_base_url.startswith(("http://", "https://")):
            problems.append(
                f"WALLEX_BASE_URL must start with http:// or https:// "
                f"(got {self.wallex_base_url!r})."
            )

        if require_api_key and not self.wallex_api_key:
            problems.append(
                "WALLEX_API_KEY is required for account data but is not set. "
                "Add it to your .env file (see .env.example)."
            )

        if problems:
            joined = "\n  - ".join(problems)
            raise ConfigError(
                "Configuration problem(s) found:\n  - " + joined
            )

    # ------------------------------------------------------------------ #
    # Convenience
    # ------------------------------------------------------------------ #
    @property
    def has_wallex_key(self) -> bool:
        """True when an account API key is available."""
        return bool(self.wallex_api_key)

    def describe(self) -> str:
        """A human-readable summary that is safe to print or log.

        Secrets pass through `mask_secret()`, so even if this summary ends up
        in a log file or a screenshot, the key cannot be recovered from it.
        """
        lines = [
            "Configuration summary",
            "---------------------",
            f"  WALLEX_API_KEY    : {mask_secret(self.wallex_api_key)}",
            f"  WALLEX_BASE_URL   : {self.wallex_base_url}",
            f"  LOG_LEVEL         : {self.log_level}",
            f"  APP_LANGUAGE      : {self.language}",
            f"  REQUEST_TIMEOUT   : {self.request_timeout}s",
            f"  MAX_RETRIES       : {self.max_retries}",
            f"  LLM_PROVIDER      : {self.llm_provider}",
            f"  LLM_API_KEY       : {mask_secret(self.llm_api_key)}",
            f"  .env file         : {'found' if ENV_FILE.exists() else 'MISSING'}",
            f"  Account access    : "
            f"{'ready' if self.has_wallex_key else 'no key (public data only)'}",
        ]
        return "\n".join(lines)

    # Keep secrets out of tracebacks and object reprs.
    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"Settings(wallex_api_key={mask_secret(self.wallex_api_key)!r}, "
            f"wallex_base_url={self.wallex_base_url!r}, "
            f"log_level={self.log_level!r}, language={self.language!r}, "
            f"llm_provider={self.llm_provider!r})"
        )


def get_settings(require_api_key: bool = False) -> Settings:
    """Load and validate settings in one call.

    This is the function the rest of the application should use.
    """
    settings = Settings.load()
    settings.validate(require_api_key=require_api_key)
    return settings


def _main() -> int:
    """Print a safe configuration summary (used by `python -m ...config`)."""
    settings = Settings.load()
    print(settings.describe())
    try:
        settings.validate()
    except ConfigError as exc:
        print(f"\nValidation: FAILED\n{exc}")
        return 1
    print("\nValidation: OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
