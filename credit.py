"""Read-only Tinyhat credit summary for the authenticated Computer owner."""

from __future__ import annotations

import json
from typing import Any

from .platform import PlatformError, build_platform_client, computer_api_path
from .tool_errors import tool_error_json

MAX_RECENT_TRANSACTIONS = 10


def credit_summary(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Return safe credit balance and recent ledger entries from Tinyhat."""
    _ = args
    try:
        client, platform_auth = build_platform_client()
        payload = client.get_json(computer_api_path(platform_auth, "credit/v1"))
        safe_payload = _safe_credit_payload(payload)
    except (PlatformError, ValueError, TypeError) as exc:
        return tool_error_json(
            tool="tinyhat_credit",
            error_name="credit_summary_unavailable",
            message=str(exc),
        )
    return json.dumps(safe_payload, sort_keys=True)


def _safe_credit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Project only the documented non-payment fields into tool output."""
    balance_cents = payload.get("balance_cents")
    if isinstance(balance_cents, bool) or not isinstance(balance_cents, int):
        raise ValueError("Tinyhat returned an invalid credit balance.")
    currency = payload.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError("Tinyhat returned an invalid credit currency.")
    raw_entries = payload.get("recent_transactions")
    if not isinstance(raw_entries, list):
        raise ValueError("Tinyhat returned an invalid credit transaction list.")

    entries: list[dict[str, Any]] = []
    for raw_entry in raw_entries[:MAX_RECENT_TRANSACTIONS]:
        if not isinstance(raw_entry, dict):
            raise ValueError("Tinyhat returned an invalid credit transaction.")
        entry_type = raw_entry.get("entry_type")
        amount_cents = raw_entry.get("amount_cents")
        entry_currency = raw_entry.get("currency")
        created_at = raw_entry.get("created_at")
        if (
            not isinstance(entry_type, str)
            or isinstance(amount_cents, bool)
            or not isinstance(amount_cents, int)
            or not isinstance(entry_currency, str)
            or not isinstance(created_at, str)
        ):
            raise ValueError("Tinyhat returned an invalid credit transaction.")
        entries.append(
            {
                "entry_type": entry_type,
                "amount_cents": amount_cents,
                "currency": entry_currency,
                "created_at": created_at,
            }
        )

    return {
        "schema": "tinyhat_credit_summary_v1",
        "balance_cents": balance_cents,
        "currency": currency,
        "recent_transactions": entries,
    }
