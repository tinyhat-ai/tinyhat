"""Thin client for assignment-scoped account upgrades; no credentials in output."""

from __future__ import annotations

import json
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


def account_upgrade(args: dict[str, Any] | None = None, **_: Any) -> str:
    payload = args if isinstance(args, dict) else {}
    action = payload.get("action", "status")
    if action not in {"status", "submit", "continue", "verification_link"}:
        return _error("invalid_action", "Use status, submit, continue, or verification_link.")
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
                {
                    "individual": payload["individual"],
                    "consent": payload["consent"],
                },
            )
        else:
            suffix = "verification-link" if action == "verification_link" else "upgrade/continue"
            result = client.post_json(f"{BASE}/{suffix}", {})
        if action == "verification_link":
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
    except PlatformError as exc:
        response = exc.response if isinstance(exc.response, dict) else {}
        error = response.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if code == "owner_email_required":
            return _error(
                code,
                "Verify your email in your existing Tinyhat profile first. In Telegram, open Configure and your Profile. Do not sign up for another account.",
            )
        if code in {"computer_owner_unavailable", "computer_owner_changed"}:
            return _error(
                code,
                "Tinyhat could not confirm this Computer's current owner. Check its assignment before retrying.",
            )
        if exc.status_code == 422:
            return _error(
                "invalid_request",
                "Check the individual's details and the current terms version. Never guess missing information or approval.",
            )
        if exc.status_code in {401, 403}:
            return _error(
                "computer_authentication_required",
                "This Computer could not authenticate. Do not use another user's credentials.",
            )
        if action == "submit":
            return _error(
                "upgrade_submission_uncertain",
                "The upgrade was not confirmed. Check status before retrying the identical request; do not create another account.",
            )
        return _error(
            "account_upgrade_unavailable",
            "Account upgrades are not available right now. Keep the existing account and check again later.",
        )
    except (TypeError, ValueError, KeyError):
        return _error(
            "invalid_platform_response",
            "Tinyhat could not confirm the upgrade. Check status before proceeding.",
        )
