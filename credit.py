"""Tinyhat credit tools for the authenticated Computer owner."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .platform import PlatformError, build_platform_client, computer_api_path
from .tool_errors import tool_error_json

MAX_RECENT_TRANSACTIONS = 10
MIN_OPENROUTER_ALLOCATION_CENTS = 100
OPENROUTER_ALLOCATION_STATUSES = {"allocated", "pending", "failed"}


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


def allocate_openrouter_credit(
    args: dict[str, Any] | None = None,
    **metadata: Any,
) -> str:
    """Allocate owner credit to this Computer's assigned Agent model budget."""
    payload = args if isinstance(args, dict) else {}
    amount_cents = payload.get("amount_cents")
    if amount_cents is None:
        return tool_error_json(
            tool="tinyhat_openrouter_credit_allocate",
            error_name="missing_required_parameter",
            message="Ask the user for the exact amount to allocate, in US dollars.",
            missing=["amount_cents"],
            example_call={"amount_cents": 500},
        )
    if (
        isinstance(amount_cents, bool)
        or not isinstance(amount_cents, int)
        or amount_cents < MIN_OPENROUTER_ALLOCATION_CENTS
    ):
        return tool_error_json(
            tool="tinyhat_openrouter_credit_allocate",
            error_name="invalid_amount",
            message="The allocation must be at least US$1.00 in whole cents.",
            expected={"amount_cents": "integer greater than or equal to 100"},
            example_call={"amount_cents": 500},
        )

    try:
        client, platform_auth = build_platform_client()
        platform_payload = client.post_json(
            computer_api_path(
                platform_auth,
                "credit/v1/openrouter-allocations",
            ),
            {
                "amount_cents": amount_cents,
                "idempotency_key": _allocation_idempotency_key(
                    metadata.get("task_id"),
                    amount_cents,
                ),
            },
        )
        safe_payload = _safe_openrouter_allocation_payload(
            platform_payload,
            expected_amount_cents=amount_cents,
        )
    except PlatformError as exc:
        return _openrouter_allocation_error(exc)
    except (ValueError, TypeError):
        return tool_error_json(
            tool="tinyhat_openrouter_credit_allocate",
            error_name="invalid_platform_response",
            message=(
                "Tinyhat returned an invalid allocation result. Do not retry "
                "automatically; ask the user to check their credit history."
            ),
        )
    return json.dumps(safe_payload, sort_keys=True)


def _allocation_idempotency_key(task_id: Any, amount_cents: int) -> str:
    """Derive a value-blind replay key from runtime metadata, never model input."""
    runtime_request = (
        task_id.strip()
        if isinstance(task_id, str) and task_id.strip()
        else uuid.uuid4().hex
    )
    digest = hashlib.sha256(
        f"tinyhat-openrouter-credit:{runtime_request}:{amount_cents}".encode("utf-8")
    ).hexdigest()
    return f"plugin_{digest}"


def _safe_openrouter_allocation_payload(
    payload: dict[str, Any],
    *,
    expected_amount_cents: int,
) -> dict[str, Any]:
    """Project only Agent-safe accounting fields from an allocation result."""
    status = payload.get("status")
    amount_cents = payload.get("amount_cents")
    balance_cents = payload.get("balance_cents")
    currency = payload.get("currency")
    openrouter_limit_cents = payload.get("openrouter_limit_cents")
    created_at = payload.get("created_at")
    if status not in OPENROUTER_ALLOCATION_STATUSES:
        raise ValueError("invalid allocation status")
    for value in (amount_cents, balance_cents):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("invalid allocation amount")
    if amount_cents != expected_amount_cents:
        raise ValueError("allocation amount does not match request")
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError("invalid allocation currency")
    if (
        openrouter_limit_cents is not None
        and (
            isinstance(openrouter_limit_cents, bool)
            or not isinstance(openrouter_limit_cents, int)
        )
    ):
        raise ValueError("invalid provider limit")
    if not isinstance(created_at, str) or not created_at.strip():
        raise ValueError("invalid allocation timestamp")
    return {
        "schema": "tinyhat_openrouter_credit_allocation_v1",
        "status": status,
        "amount_cents": amount_cents,
        "balance_cents": balance_cents,
        "currency": currency,
        "openrouter_limit_cents": openrouter_limit_cents,
        "created_at": created_at,
    }


def _openrouter_allocation_error(exc: PlatformError) -> str:
    """Return stable, value-blind errors without echoing platform responses."""
    if exc.status_code == 402:
        error_name = "insufficient_credit"
        message = "The user does not have enough Tinyhat credit for this allocation."
    elif exc.status_code == 404:
        error_name = "openrouter_key_unavailable"
        message = "This Agent does not have an OpenRouter model key available to fund."
    elif exc.status_code == 409:
        error_name = "allocation_conflict"
        message = (
            "Tinyhat could not safely start this allocation. Check the current "
            "balance and recent transactions before trying a new request."
        )
    else:
        error_name = "openrouter_credit_allocation_unavailable"
        message = (
            "Tinyhat could not confirm the allocation. Do not retry automatically; "
            "ask the user to check their credit history."
        )
    return tool_error_json(
        tool="tinyhat_openrouter_credit_allocate",
        error_name=error_name,
        message=message,
    )


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
