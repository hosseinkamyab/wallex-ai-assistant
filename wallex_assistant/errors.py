"""Exception types for the Wallex API layer.

Centralising exceptions means calling code can catch precisely what it cares
about, without guessing at `requests` internals:

    try:
        ticker = client.get_ticker("BTCTMN")
    except WallexAuthError:
        # the key is wrong -- tell the user, don't retry
    except WallexRateLimitError:
        # slow down -- safe to retry later
    except WallexError:
        # anything else from this API

The hierarchy:

    WallexError                 <- catch this to catch everything from Wallex
    ├── WallexNetworkError      <- could not reach / connection dropped
    ├── WallexAPIError          <- the API answered, but with an error
    │   ├── WallexAuthError     <- 401/403: bad or missing key
    │   ├── WallexNotFoundError <- 404: unknown symbol or endpoint
    │   └── WallexRateLimitError<- 429: too many requests, back off
    └── WallexResponseError     <- the response was not what we expected

Why bother? Because "something went wrong" is not actionable. "The key is
wrong, retrying won't help" and "you are being rate-limited, wait 30 seconds"
lead to completely different responses -- in code and in the UI.
"""

from __future__ import annotations


class WallexError(Exception):
    """Base class for every error raised by this project's Wallex layer."""


class WallexNetworkError(WallexError):
    """We could not talk to Wallex: DNS, timeout, connection reset.

    Typically transient, so the HTTP layer retries these automatically.
    """


class WallexAPIError(WallexError):
    """Wallex answered, but reported a problem.

    Attributes:
        message: Human-readable description from the API or from us.
        status_code: HTTP status, when there was one.
        endpoint: The path that failed, e.g. "/v1/markets". Never includes
            credentials or the full query string.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        endpoint: str | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.endpoint = endpoint
        detail = message
        if status_code is not None:
            detail = f"[HTTP {status_code}] {message}"
        if endpoint:
            detail = f"{detail} (endpoint: {endpoint})"
        super().__init__(detail)


class WallexAuthError(WallexAPIError):
    """The API key is missing, invalid, or lacks permission (401/403)."""


class WallexNotFoundError(WallexAPIError):
    """Unknown symbol or endpoint (404)."""


class WallexRateLimitError(WallexAPIError):
    """Too many requests (429). Retrying immediately makes it worse.

    Attributes:
        retry_after: Seconds to wait, if the server told us.
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        *,
        retry_after: float | None = None,
        status_code: int | None = 429,
        endpoint: str | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(message, status_code=status_code, endpoint=endpoint)


class WallexResponseError(WallexAPIError):
    """The response arrived but did not have the shape we expected.

    Usually means the API changed. The message says which field was missing,
    so it is easy to fix once you have looked at the raw payload (which is
    exactly what `python -m wallex_assistant.market_client --probe` prints).
    """


class ReadOnlyViolation(WallexError):
    """Code tried to do something this application must never do.

    This is a *programming* error, not a network error: it means a call was
    attempted that is not on the read-only allowlist, or used a method other
    than GET. It exists so a future bug -- or a well-meaning future change --
    fails loudly here instead of quietly touching your funds.

    It is deliberately NOT a subclass of WallexAPIError, because it never
    reaches the network at all.
    """
