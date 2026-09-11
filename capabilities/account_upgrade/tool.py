"""Thin client for assignment-scoped account upgrades; no credentials in output."""

from __future__ import annotations

import json
from http.client import HTTPException
from typing import Any
from urllib.parse import urlparse

from ...platform import PlatformError, build_platform_client
from ...tool_errors import tool_error_json

BASE = "/hapi/v2/computers/me/account"
APPROVALS = (
    "tinyhat_terms_accepted",
    "stripe_terms_accepted",
    "personal_data_sharing_accepted",
    "identity_verification_accepted",
    "human_authorized",
)
STATUS_FIELDS = {
    "available",
    "status",
    "stage",
    "message",
    "requirements",
    "spending_limit_cents",
    "reserved_limit_cents",
    "available_limit_cents",
    "currency",
    "interval",
    "terms_version",
    "tinyhat_terms_url",
    "stripe_terms_url",
    "stripe_privacy_url",
    "stripe_disclosure_url",
    "retry_after_seconds",
    "checked_at",
}


def _error(code: str, message: str) -> str:
    return tool_error_json(tool="tinyhat_account_upgrade", error_name=code, message=message)


def _validate(payload: dict[str, Any], action: str) -> str | None:
    allowed = {"action", "individual", "consent"} if action == "submit" else {"action"}
    if set(payload) - allowed:
        return _error(
            "invalid_arguments",
            "This tool uses only the currently assigned owner; do not supply account or user identifiers.",
        )
    if action == "submit":
        consent = payload.get("consent")
        if (
            not isinstance(consent, dict)
            or any(consent.get(key) is not True for key in APPROVALS)
            or not isinstance(consent.get("terms_version"), str)
            or not consent["terms_version"]
        ):
            return _error(
                "human_approval_required",
                "Explain the current upgrade terms and obtain the human's express approval before submitting.",
            )
        if not isinstance(payload.get("individual"), dict):
            return _error(
                "individual_details_required",
                "Ask for the individual's accurate details or offer the private upgrade form.",
            )
    return None


def _request_failure(action: str, exc: Exception) -> str:
    known = {
        "owner_email_required": "Verify your email in your existing Tinyhat profile first. In Telegram, open Configure and your Profile. Do not sign up for another account.",
        "computer_owner_unavailable": "Tinyhat could not confirm this Computer's current owner. Check its assignment before retrying.",
        "computer_owner_changed": "Tinyhat could not confirm this Computer's current owner. Check its assignment before retrying.",
    }
    response = (
        exc.response if isinstance(exc, PlatformError) and isinstance(exc.response, dict) else {}
    )
    error = response.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, str) and code in known:
        return _error(code, known[code])
    status = exc.status_code if isinstance(exc, PlatformError) else None
    statuses = {
        429: (
            "account_upgrade_rate_limited",
            "Tinyhat is limiting requests. Wait at least one minute, then check status; do not resubmit now.",
        ),
        409: (
            "account_upgrade_conflict",
            "Check status before proceeding. Keep the existing upgrade and do not submit changed details.",
        ),
        422: (
            "invalid_request",
            "Check the individual's details and the current terms version. Never guess missing information or approval.",
        ),
        401: (
            "computer_authentication_required",
            "This Computer could not authenticate. Do not use another user's credentials.",
        ),
        403: (
            "computer_authentication_required",
            "This Computer could not authenticate. Do not use another user's credentials.",
        ),
    }
    if status in statuses:
        return _error(*statuses[status])
    if action == "submit":
        return _error(
            "upgrade_submission_uncertain",
            "The upgrade was not confirmed. Check status before retrying the identical request; do not create another account.",
        )
    return _error(
        "account_upgrade_unavailable",
        "Tinyhat could not confirm the upgrade. Check status later before proceeding; do not create another account.",
    )


def _verification_link(result: dict[str, Any]) -> str:
    url = result.get("url", "")
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "connect.stripe.com"
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
    ):
        raise ValueError("invalid verification URL")
    return json.dumps({"url": url})


def _safe_result(action: str, result: dict[str, Any]) -> str:
    if action == "verification_link":
        return _verification_link(result)
    if result.get("status") not in {
        "not_started",
        "pending",
        "needs_information",
        "ready",
        "setup_required",
        "recovery_required",
    }:
        raise ValueError("invalid status")
    return json.dumps(
        {key: value for key, value in result.items() if key in STATUS_FIELDS}, sort_keys=True
    )


def account_upgrade(args: dict[str, Any] | None = None, **_: Any) -> str:
    payload = args if isinstance(args, dict) else {}
    action = payload.get("action", "status")
    if not isinstance(action, str) or action not in {
        "status",
        "submit",
        "continue",
        "verification_link",
    }:
        return _error("invalid_action", "Use status, submit, continue, or verification_link.")
    invalid = _validate(payload, action)
    if invalid:
        return invalid
    try:
        client, authentication = build_platform_client(timeout_seconds=45)
        if authentication != "gcloud":
            return _error(
                "computer_identity_required",
                "Use this tool from the assigned Tinyhat cloud Computer.",
            )
        if action == "status":
            result = client.get_json(f"{BASE}/upgrade")
        elif action == "submit":
            result = client.post_json(
                f"{BASE}/upgrade",
                {"individual": payload["individual"], "consent": payload["consent"]},
            )
        else:
            suffix = "verification-link" if action == "verification_link" else "upgrade/continue"
            result = client.post_json(f"{BASE}/{suffix}", {})
        return _safe_result(action, result)
    except (PlatformError, OSError, HTTPException) as exc:
        # A response may be lost after acceptance. Never echo or retry a write.
        return _request_failure(action, exc)
    except (TypeError, ValueError, KeyError):
        return _error(
            "invalid_platform_response",
            "Tinyhat could not confirm the upgrade. Check status before proceeding.",
        )
