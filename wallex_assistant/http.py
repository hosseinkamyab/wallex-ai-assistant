"""HTTP transport for the Wallex API.

One small class that owns every detail of *talking* to the network, so the
clients built on top (market, account) contain only API logic:

* a single reusable `requests.Session` (connection pooling -- faster)
* explicit timeouts, always (a request with no timeout can hang forever)
* automatic retries with exponential backoff for *transient* failures only
* translation of HTTP status codes into our `errors.py` exception types
* logging that never includes credentials

An important distinction this module enforces: **retry only what is safe to
retry.** A timeout or a 500 is worth retrying. A 401 (bad key) is not -- it
will fail identically every time, so retrying just wastes time and can get you
rate-limited. Because everything here is read-only (GET), retrying is always
safe; there is no risk of creating a duplicate order.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import requests

from .errors import (
    WallexAPIError,
    WallexAuthError,
    WallexNetworkError,
    WallexNotFoundError,
    WallexRateLimitError,
    WallexResponseError,
)


logger = logging.getLogger(__name__)

# Status codes worth trying again.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class WallexHttpClient:
    """A thin, well-behaved wrapper around `requests`.

    Args:
        base_url: API root, e.g. "https://api.wallex.ir".
        api_key: Optional. Sent as the `x-api-key` header when present.
        timeout: Per-request timeout in seconds.
        max_retries: How many *additional* attempts after the first.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        timeout: int = 15,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, max_retries)

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "wallex-ai-assistant/0.1 (read-only)",
            }
        )
        # The key goes in a header, never in the URL: URLs end up in logs,
        # browser history and error messages far more often than headers do.
        if api_key:
            self._session.headers["x-api-key"] = api_key
        self._has_key = bool(api_key)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Perform a GET request and return the unwrapped payload.

        Args:
            path: Endpoint path beginning with "/", e.g. "/v1/markets".
            params: Query parameters.

        Returns:
            The useful part of the JSON body (normally `result`).

        Raises:
            WallexNetworkError: unreachable after all retries.
            WallexAuthError / WallexNotFoundError / WallexRateLimitError:
                for 401, 403, 404 and 429.
            WallexAPIError: any other API-reported failure.
            WallexResponseError: unparseable or unexpectedly shaped response.
        """
        if not path.startswith("/"):
            path = "/" + path

        url = f"{self.base_url}{path}"
        attempt = 0
        pending_delay: float | None = None

        while True:
            if attempt:
                # Sleep *once* per retry. `pending_delay` lets a rate-limit
                # response dictate the wait instead of guessing.
                time.sleep(
                    pending_delay
                    if pending_delay is not None
                    else self._backoff_delay(attempt)
                )
            pending_delay = None

            try:
                response = self._session.get(
                    url, params=params, timeout=self.timeout
                )
                return self._handle_response(response, path)

            except WallexAPIError as exc:
                # Wallex answered with an error. Retry only if it is the kind
                # of failure that might succeed next time.
                if not self._is_retryable(exc) or attempt >= self.max_retries:
                    raise
                pending_delay = getattr(exc, "retry_after", None) or \
                    self._backoff_delay(attempt + 1)
                attempt += 1
                logger.warning(
                    "Retryable error on %s (%s); retry %d/%d in %.1fs",
                    path, exc, attempt, self.max_retries, pending_delay,
                )

            except requests.RequestException as exc:
                # Connection refused, DNS failure, timeout, reset. These are
                # almost always transient, so wrap and retry.
                if attempt >= self.max_retries:
                    raise WallexNetworkError(
                        f"Could not reach Wallex after "
                        f"{self.max_retries + 1} attempts: {exc}"
                    ) from exc
                attempt += 1
                logger.warning(
                    "Network error on %s (attempt %d/%d): %s",
                    path, attempt, self.max_retries + 1, exc,
                )

    @staticmethod
    def _is_retryable(exc: WallexAPIError) -> bool:
        """True only for failures that might succeed on a second attempt.

        A bad key (401), an unknown symbol (404) or a changed response shape
        will fail identically every time -- retrying them just wastes time and
        can push us into rate limiting.
        """
        if isinstance(exc, WallexRateLimitError):
            return True
        if isinstance(exc, WallexResponseError):
            # The API replied sensibly; our parsing did not match. Not a
            # transient condition.
            return False
        return exc.status_code in RETRYABLE_STATUS

    def close(self) -> None:
        """Release the underlying connection pool."""
        self._session.close()

    def __enter__(self) -> "WallexHttpClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with jitter.

        0.5s, 1s, 2s, 4s ... plus a random fraction, capped at 8 seconds. The
        jitter matters: without it, several clients that fail together would
        all retry at the same instant and hammer the API in lockstep.
        """
        base = min(0.5 * (2 ** (attempt - 1)), 8.0)
        return base + random.uniform(0, 0.3)

    def _handle_response(
        self, response: requests.Response, path: str
    ) -> dict[str, Any]:
        """Turn a `requests.Response` into data or one of our exceptions."""
        status = response.status_code

        if status >= 400:
            raise self._error_for_status(response, path)

        try:
            payload = response.json()
        except ValueError as exc:
            snippet = (response.text or "")[:200]
            raise WallexResponseError(
                f"Response was not valid JSON. First 200 chars: {snippet!r}",
                status_code=status,
                endpoint=path,
            ) from exc

        if not isinstance(payload, dict):
            raise WallexResponseError(
                f"Expected a JSON object, got {type(payload).__name__}",
                status_code=status,
                endpoint=path,
            )

        return self._unwrap(payload, path, status)

    def _error_for_status(
        self, response: requests.Response, path: str
    ) -> WallexAPIError:
        """Map an HTTP error status onto the most specific exception."""
        status = response.status_code
        message = self._extract_message(response)

        if status in (401, 403):
            hint = (
                "" if self._has_key
                else " (no API key was supplied -- this endpoint needs one)"
            )
            return WallexAuthError(
                f"{message}{hint}", status_code=status, endpoint=path
            )

        if status == 404:
            return WallexNotFoundError(
                message, status_code=status, endpoint=path
            )

        if status == 429:
            return WallexRateLimitError(
                message,
                retry_after=self._retry_after(response),
                status_code=status,
                endpoint=path,
            )

        return WallexAPIError(message, status_code=status, endpoint=path)

    @staticmethod
    def _retry_after(response: requests.Response) -> float | None:
        """Read the Retry-After header, if present and sane."""
        raw = response.headers.get("Retry-After")
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            return None
        # Guard against an absurd value locking the app for hours.
        return value if 0 < value <= 120 else None

    @staticmethod
    def _extract_message(response: requests.Response) -> str:
        """Best-effort human-readable error message from the body."""
        try:
            body = response.json()
        except ValueError:
            text = (response.text or "").strip()
            return text[:200] or f"HTTP {response.status_code}"

        if isinstance(body, dict):
            for key in ("message", "error", "detail", "description"):
                value = body.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return f"HTTP {response.status_code}"

    @staticmethod
    def _unwrap(
        payload: dict[str, Any], path: str, status: int
    ) -> dict[str, Any]:
        """Peel off the API's response envelope.

        Wallex wraps most responses like:

            {"success": true, "message": "ok", "result": { ... }}

        but a few endpoints (the chart history one) return a bare
        TradingView-style object with no envelope. So we are deliberately
        tolerant: raise only when the body explicitly reports failure, and
        return `result` only when it is actually present.

        Callers that need a specific field should still check for it -- this
        method cannot know what each endpoint promises.
        """
        if payload.get("success") is False:
            message = (
                payload.get("message")
                or payload.get("error")
                or "API reported failure"
            )
            raise WallexAPIError(
                str(message), status_code=status, endpoint=path
            )

        result = payload.get("result")
        if isinstance(result, dict):
            return result

        # No envelope: hand back the body unchanged.
        return payload
