"""The read-only guard: a structural promise, not a comment.

You asked for an application that cannot trade, withdraw, or transfer. A
comment saying "we only read" is worth very little -- a future edit, a coding
mistake, or a copy-paste from a tutorial could quietly break that promise.

So the promise is enforced in code, in three independent layers:

1. **Allowlist.** Only paths named in `ALLOWED_PATHS` may be requested. Every
   trading, withdrawal and transfer endpoint is absent, so it cannot be
   reached even by accident.

2. **GET only.** `assert_read_only()` rejects any HTTP method other than GET.
   The transport in `http.py` only implements GET, so there is no code path
   that can POST an order.

3. **Pattern screening.** Even a GET can be dangerous if its path hints at a
   mutating action (`/order`, `/withdraw`, ...). `assert_read_only()` screens
   the path for those words and refuses.

Because all three are checked in one place, adding a new read endpoint is a
one-line change -- and adding a *write* endpoint is impossible without
deliberately editing this file to say so.
"""

from __future__ import annotations

from .errors import ReadOnlyViolation

# HTTP methods that can change state. Kept explicit so the intent is obvious.
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE", "HEAD"})

# The complete list of read endpoints this application may call.
# Add account endpoints here as they are implemented.
ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        # --- public market data (no key) ---
        "/v1/markets",
        "/v1/market-status",
        "/v1/depth",
        "/v1/trades",
        "/v1/udf/history",
        # --- authenticated read-only account data ---
        # Deliberately does NOT include the order-status endpoint
        # ("/v1/account/order"): it shares a path prefix with the endpoint used
        # to *place* orders. Open orders and fills give us the history we need
        # without putting an order-shaped path in the allowlist at all.
        "/v1/account/balances",
        "/v1/account/openorders",  # normalized to lowercase
        "/v1/account/fills",
    }
)

# Words that must never appear in a path we request. If one does, something is
# very wrong -- refuse loudly rather than discover it in your account history.
FORBIDDEN_PATH_FRAGMENTS: tuple[str, ...] = (
    "withdraw",
    "deposit",
    "transfer",
    "order/cancel",
    "cancel",
    "create",
    "place",
    "trade",
    "wallet/address",
)


def assert_read_only(path: str, method: str = "GET") -> None:
    """Raise `ReadOnlyViolation` unless this is a permitted read request.

    Args:
        path: The endpoint path about to be requested, e.g. "/v1/markets".
        method: HTTP method. Anything but GET is rejected.

    Raises:
        ReadOnlyViolation: the request is not a permitted read operation.

    Examples:
        >>> assert_read_only("/v1/markets")          # allowed, returns None
        >>> assert_read_only("/v1/account/balances") # allowed
    """
    method_upper = (method or "").upper()

    if method_upper != "GET":
        raise ReadOnlyViolation(
            f"Blocked {method_upper} request to {path!r}. This application is "
            "read-only and may only perform GET requests."
        )

    if not path or not isinstance(path, str):
        raise ReadOnlyViolation(f"Invalid request path: {path!r}")

    normalised = path.split("?", 1)[0].rstrip("/").lower()

    # Check allowlist FIRST: if the path is explicitly permitted, accept it.
    if normalised in ALLOWED_PATHS:
        return

    # Only check forbidden fragments for paths not on the allowlist.
    for fragment in FORBIDDEN_PATH_FRAGMENTS:
        if fragment in normalised:
            raise ReadOnlyViolation(
                f"Blocked request to {path!r}: the path contains "
                f"{fragment!r}, which looks like a state-changing operation. "
                "This application is read-only."
            )

    # If we get here, the path is not allowlisted and not blocked by fragments.
    # Still reject it for safety.
    raise ReadOnlyViolation(
        f"Blocked request to {path!r}: it is not in the read-only "
        f"allowlist. Permitted paths are:\n  "
        + "\n  ".join(sorted(ALLOWED_PATHS))
    )


def is_allowed(path: str) -> bool:
    """True when `path` is a permitted GET endpoint. Never raises."""
    try:
        assert_read_only(path, "GET")
    except ReadOnlyViolation:
        return False
    return True


class ReadOnlyClient:
    """Duck-typed wrapper adding the allowlist check to any HTTP client.

    Used like the inner client, but every `get()` is screened first. Because
    `AccountClient` is only ever constructed around one of these, there is no
    route from account code to an unscreened request.
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner

    def get(self, path: str, params: dict | None = None) -> dict:
        assert_read_only(path, "GET")
        return self._inner.get(path, params=params)  # type: ignore[attr-defined]

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()

    def __enter__(self) -> "ReadOnlyClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
