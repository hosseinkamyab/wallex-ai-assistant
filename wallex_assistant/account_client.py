"""Read-only client for your Wallex *account* data.

This is the only module that uses your API key, and it can only read. Every
request passes through `readonly.ReadOnlyClient`, which rejects anything that
is not a GET against an allowlisted path. There is no code in this file that
can place an order, cancel one, withdraw, or transfer -- and no way to add one
without editing `readonly.py` deliberately.

Three endpoints are exposed:

    GET /v1/account/balances     what you hold
    GET /v1/account/openOrders   orders still resting on the book
    GET /v1/account/fills        your trade history

A note on why balances are the tricky one: the API returns quantities, but a
quantity alone is meaningless ("I have 0.0041 BTC" -- worth what?). Valuation
against live prices happens in Stage 3, kept deliberately separate so that
this module stays a thin, honest mirror of what the exchange reports.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .config import ConfigError, Settings, get_settings
from .errors import ReadOnlyViolation, WallexError, WallexResponseError
from .http import WallexHttpClient
from .logging_setup import setup_logging
from .market_client import MarketClient
from .readonly import ReadOnlyClient

logger = logging.getLogger(__name__)


def _to_decimal_safe(value: Any) -> Decimal | None:
    """Convert to Decimal, or None. Balances must never crash on odd input."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


@dataclass(frozen=True)
class Balance:
    """One asset holding, exactly as the exchange reports it.

    `locked` is funds tied up in open orders; `available` is free to use.
    `total` is the sum, and is what valuation should use -- counting only
    `available` would understate your holdings whenever you have open orders.
    """

    asset: str
    available: Decimal = Decimal("0")
    locked: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.available + self.locked

    @property
    def is_empty(self) -> bool:
        """True when there is nothing here (dust shows up more than you'd like)."""
        return self.total == 0

    @classmethod
    def from_api(cls, asset: str, raw: dict[str, Any]) -> "Balance":
        """Build from one entry of the balances response.

        Wallex reports these as string numbers. Field names differ between
        camelCase and snake_case, so both are accepted.
        """
        available = _to_decimal_safe(
            raw.get("available", raw.get("balance", raw.get("free")))
        )
        locked = _to_decimal_safe(raw.get("locked", raw.get("inOrder", 0)))
        total = _to_decimal_safe(raw.get("total", raw.get("value")))

        if total is not None and (
            available is None or (available + (locked or Decimal("0"))) == 0
        ):
            # Only a total was given: treat it as fully available.
            available = total

        return cls(
            asset=asset,
            available=available or Decimal("0"),
            locked=locked or Decimal("0"),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "asset": self.asset,
            "available": str(self.available),
            "locked": str(self.locked),
            "total": str(self.total),
        }


@dataclass(frozen=True)
class Order:
    """An open order on the book."""

    order_id: str
    symbol: str | None = None
    side: str | None = None            # "buy" / "sell"
    price: Decimal | None = None
    quantity: Decimal | None = None
    executed_quantity: Decimal | None = None
    created_at: datetime | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Order":
        return cls(
            order_id=str(
                raw.get("id")
                or raw.get("orderId")
                or raw.get("order_id")
                or "unknown"
            ),
            symbol=raw.get("symbol") or raw.get("market"),
            side=raw.get("side") or raw.get("type"),
            price=_to_decimal_safe(raw.get("price")),
            quantity=_to_decimal_safe(
                raw.get("quantity") or raw.get("origQty") or raw.get("amount")
            ),
            executed_quantity=_to_decimal_safe(
                raw.get("executedQuantity")
                or raw.get("executedQty")
                or raw.get("filled")
            ),
            created_at=_parse_timestamp(
                raw.get("createdAt") or raw.get("created_at")
                or raw.get("timestamp") or raw.get("time")
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "price": None if self.price is None else str(self.price),
            "quantity": None if self.quantity is None else str(self.quantity),
            "executed_quantity": (
                None if self.executed_quantity is None
                else str(self.executed_quantity)
            ),
            "created_at": (
                None if self.created_at is None
                else self.created_at.isoformat()
            ),
        }


@dataclass(frozen=True)
class Fill:
    """A completed trade (part of or all of an order)."""

    fill_id: str
    symbol: str | None = None
    side: str | None = None
    price: Decimal | None = None
    quantity: Decimal | None = None
    fee: Decimal | None = None
    fee_asset: str | None = None
    executed_at: datetime | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Fill":
        return cls(
            fill_id=str(
                raw.get("id") or raw.get("tradeId") or raw.get("fillId") or "?"
            ),
            symbol=raw.get("symbol") or raw.get("market"),
            side=raw.get("side") or raw.get("type"),
            price=_to_decimal_safe(raw.get("price")),
            quantity=_to_decimal_safe(
                raw.get("quantity") or raw.get("qty") or raw.get("amount")
            ),
            fee=_to_decimal_safe(raw.get("fee") or raw.get("commission")),
            fee_asset=raw.get("feeAsset") or raw.get("commissionAsset"),
            executed_at=_parse_timestamp(
                raw.get("timestamp") or raw.get("time")
                or raw.get("createdAt") or raw.get("executedAt")
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "fill_id": self.fill_id,
            "symbol": self.symbol,
            "side": self.side,
            "price": None if self.price is None else str(self.price),
            "quantity": None if self.quantity is None else str(self.quantity),
            "fee": None if self.fee is None else str(self.fee),
            "fee_asset": self.fee_asset,
            "executed_at": (
                None if self.executed_at is None
                else self.executed_at.isoformat()
            ),
        }


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse a timestamp given as epoch seconds, epoch ms, or ISO text."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            number = float(value)
        else:
            text = str(value).strip()
            if text.isdigit():
                number = float(text)
            else:
                # ISO 8601, possibly with a trailing Z.
                return datetime.fromisoformat(text.replace("Z", "+00:00"))

        # Milliseconds if it looks far too large to be seconds.
        if number > 1e11:
            number /= 1000
        return datetime.fromtimestamp(number, tz=timezone.utc)
    except (ValueError, TypeError, OSError, OverflowError):
        return None


class AccountClient:
    """Read-only access to your Wallex account data."""

    def __init__(self, client: ReadOnlyClient) -> None:
        # Note the type: it is a *guarded* client, not the raw HTTP client.
        # That means every call is screened by the allowlist.
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "AccountClient":
        """Build an account client. Raises ConfigError without a key.

        The key is mandatory here (unlike market data), and validation runs
        immediately -- failing at startup with a clear message beats failing
        with a 401 halfway through a page load.
        """
        settings = settings or get_settings()
        settings.validate(require_api_key=True)

        if not settings.wallex_api_key:
            # Defensive: validate() already covers this, but this method is
            # security-relevant so it does not rely on a caller's assumption.
            raise ConfigError(
                "WALLEX_API_KEY is not set. Account data requires an API key; "
                "see .env.example."
            )

        http = WallexHttpClient(
            base_url=settings.wallex_base_url,
            api_key=settings.wallex_api_key,
            timeout=settings.request_timeout,
            max_retries=settings.max_retries,
        )
        return cls(ReadOnlyClient(http))

    # ------------------------------------------------------------------ #
    # Endpoints
    # ------------------------------------------------------------------ #
    def get_balances(self) -> list[Balance]:
        """All non-empty asset balances, largest first.

        Empty (dust) balances are filtered out by default -- Wallex can return
        dozens of zero-value assets, and they only add noise to a dashboard.
        """
        raw = self._client.get("/v1/account/balances")
        entries = raw.get("balances") or raw.get("result") or raw

        parsed: list[Balance] = []
        if isinstance(entries, dict):
            for asset, data in entries.items():
                if isinstance(data, dict):
                    parsed.append(Balance.from_api(asset, data))
                else:
                    # A bare number means "this much of the asset".
                    parsed.append(
                        Balance(asset=asset,
                                available=_to_decimal_safe(data) or Decimal("0"))
                    )
        elif isinstance(entries, list):
            for item in entries:
                if not isinstance(item, dict):
                    continue
                asset = (
                    item.get("asset") or item.get("symbol")
                    or item.get("currency") or "?"
                )
                parsed.append(Balance.from_api(str(asset), item))
        else:
            raise WallexResponseError(
                "Balances response was neither a mapping nor a list. "
                "Run --probe to inspect the shape."
            )

        non_empty = [b for b in parsed if not b.is_empty]
        non_empty.sort(key=lambda b: b.asset)
        logger.info(
            "Fetched %d non-empty balances (of %d reported)",
            len(non_empty), len(parsed),
        )
        return non_empty

    def get_open_orders(self) -> list[Order]:
        """Orders still resting on the book."""
        raw = self._client.get("/v1/account/openOrders")
        items = raw.get("orders") or raw.get("openOrders") or raw
        if isinstance(items, dict):
            items = items.get("orders", [])
        if not isinstance(items, list):
            raise WallexResponseError(
                "Open-orders response was not a list. Run --probe to inspect."
            )
        return [Order.from_api(i) for i in items if isinstance(i, dict)]

    def get_fills(self) -> list[Fill]:
        """Completed trades, most recent behaviour left to the API."""
        raw = self._client.get("/v1/account/fills")
        items = raw.get("fills") or raw.get("trades") or raw
        if isinstance(items, dict):
            items = items.get("fills", [])
        if not isinstance(items, list):
            raise WallexResponseError(
                "Fills response was not a list. Run --probe to inspect."
            )
        return [Fill.from_api(i) for i in items if isinstance(i, dict)]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AccountClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    """Inspect account data from the terminal.

        python -m wallex_assistant.account_client --balances
        python -m wallex_assistant.account_client --orders
        python -m wallex_assistant.account_client --fills
        python -m wallex_assistant.account_client --probe
        python -m wallex_assistant.account_client --analyze
    """
    parser = argparse.ArgumentParser(
        description="Inspect your Wallex account, read-only."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--balances", action="store_true")
    group.add_argument("--orders", action="store_true")
    group.add_argument("--fills", action="store_true")
    group.add_argument(
        "--probe", action="store_true",
        help="Dump raw JSON for each account endpoint.",
    )
    group.add_argument(
        "--json", action="store_true", help="Print balances as JSON."
    )
    group.add_argument(
        "--analyze", action="store_true",
        help="Show AI-powered portfolio analysis (requires LLM provider).",
    )
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"Configuration error:\n{exc}", file=sys.stderr)
        return 2

    setup_logging(settings.log_level, log_to_file=False)

    try:
        client = AccountClient.from_settings(settings)
    except ConfigError as exc:
        print(f"Cannot access account data:\n{exc}", file=sys.stderr)
        return 2

    try:
        if args.probe:
            for path in (
                "/v1/account/balances",
                "/v1/account/openOrders",
                "/v1/account/fills",
            ):
                print(f"\n{'=' * 70}\nGET {path}\n{'=' * 70}")
                try:
                    payload = client._client.get(path)  # noqa: SLF001
                    print(json.dumps(payload, indent=2, default=str)[:2000])
                except WallexError as exc:
                    print(f"FAILED: {exc}")
            return 0

        if args.balances or args.json:
            balances = client.get_balances()
            if args.json:
                print(json.dumps([b.as_dict() for b in balances], indent=2))
            else:
                print(f"{len(balances)} non-empty balances:")
                print(f"  {'ASSET':<10} {'AVAILABLE':>20} {'LOCKED':>15}")
                for bal in balances:
                    print(
                        f"  {bal.asset:<10} {bal.available:>20} "
                        f"{bal.locked:>15}"
                    )

        elif args.orders:
            orders = client.get_open_orders()
            print(f"{len(orders)} open orders:")
            for order in orders:
                print(
                    f"  {order.symbol} {order.side} "
                    f"{order.quantity} @ {order.price}"
                )

        elif args.fills:
            fills = client.get_fills()
            print(f"{len(fills)} fills:")
            for fill in fills:
                print(
                    f"  {fill.symbol} {fill.side} "
                    f"{fill.quantity} @ {fill.price}"
                )

        elif args.analyze:
            from wallex_assistant.portfolio import generate_analysis

            settings = get_settings()
            market_stats = MarketClient.from_settings(settings).get_market_stats()
            analysis = generate_analysis(
                balances=client.get_balances(),
                market_stats=market_stats,
                language=settings.language,
                model=settings.llm_provider,
            )
            print(analysis)

    except ReadOnlyViolation as exc:
        # Should be impossible; if it happens, something is wrong in the code.
        print(f"Blocked by read-only guard: {exc}", file=sys.stderr)
        return 3
    except WallexError as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
