"""Logging setup for the whole application.

Call `setup_logging()` once, early (the entry point or the Streamlit app).
Every module then just does:

    import logging
    logger = logging.getLogger(__name__)

and gets consistent formatting, without every module configuring handlers.

Why this matters: `print()` is fine for a throwaway script, but a real app
needs timestamps, severity levels, and a record on disk you can inspect after
something went wrong.

Where logs go:

* The console, so you see what is happening while you run things.
* `logs/wallex_assistant.log`, rotated (a new file once it grows), so a long
  session does not fill your disk and old logs are cleaned up automatically.

Secrets are never logged -- see `config.mask_secret()`.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from .config import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "wallex_assistant.log"

# Format: timestamp | level | module | message
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Third-party libraries are noisy at DEBUG. Keep them at WARNING unless you
# specifically want to trace HTTP internals.
NOISY_LOGGERS = ("urllib3", "requests", "charset_normalizer", "watchdog")

_configured = False


def setup_logging(level: str = "INFO", log_to_file: bool = True) -> logging.Logger:
    """Configure root logging. Safe to call more than once.

    Args:
        level: One of DEBUG, INFO, WARNING, ERROR, CRITICAL.
        log_to_file: Also write to `logs/wallex_assistant.log`.

    Returns:
        The configured root logger.

    On Streamlit, the process re-runs this file often, so we guard against
    adding a duplicate handler on every run (`_configured`). Duplicate handlers
    cause every line to appear two, four, eight times -- a classic annoyance.
    """
    global _configured

    numeric_level = getattr(logging, str(level).upper(), logging.INFO)
    root = logging.getLogger()

    if _configured:
        root.setLevel(numeric_level)
        return root

    root.setLevel(numeric_level)

    # Remove any handlers a previous configuration (or library) installed,
    # so our output format is the only one in use.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    # --- Console ---------------------------------------------------------
    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    # --- Rotating file ---------------------------------------------------
    if log_to_file:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                LOG_FILE,
                maxBytes=1_000_000,  # ~1 MB per file
                backupCount=3,       # keep 3 old files
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            # Logging should never be the reason the app dies. If the directory
            # is not writable we carry on with console logging only.
            root.warning("Could not open log file %s: %s", LOG_FILE, exc)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).debug(
        "Logging initialised at level %s", logging.getLevelName(numeric_level)
    )
    return root


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper so modules have one import instead of two."""
    return logging.getLogger(name)
