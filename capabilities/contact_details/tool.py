"""Tinyhat managed contact details for the authenticated Computer's Agent."""

from __future__ import annotations

import json
from typing import Any

from ...platform import PlatformError, build_platform_client, computer_api_path
from ...tool_errors import tool_error_json

PHONE_STATUSES = {
    "assigned",
    "disabled",
    "error",
    "not_available",
    "provisioning",
    "unavailable",
}
EMAIL_STATUSES = {
    "assigned",
    "disabled",
    "not_assigned",
    "not_available",
    "unavailable",
}


def contact_details(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Return or assign this Agent's enabled managed phone and email."""

    _ = args
    try:
        client, platform_auth = build_platform_client()
        payload = client.post_json(
            computer_api_path(platform_auth, "contact-details/v1"),
            {},
        )
        safe_payload = _safe_contact_details_payload(payload)
    except PlatformError:
        return tool_error_json(
            tool="tinyhat_contact_details",
            error_name="contact_details_unavailable",
            message="Tinyhat could not check this Agent's contact details right now.",
        )
    except (TypeError, ValueError):
        return tool_error_json(
            tool="tinyhat_contact_details",
            error_name="invalid_platform_response",
            message="Tinyhat returned an invalid contact details result.",
        )
    return json.dumps(safe_payload, sort_keys=True)


def _optional_text(value: Any, *, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid contact value")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum:
        raise ValueError("invalid contact value")
    return cleaned


def _safe_contact_details_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Project only contact values and plain status; never inventory metadata."""

    if not isinstance(payload, dict):
        raise ValueError("invalid contact response")
    phone = payload.get("phone")
    email = payload.get("email")
    if not isinstance(phone, dict) or not isinstance(email, dict):
        raise ValueError("invalid contact response")

    phone_status = phone.get("status")
    email_status = email.get("status")
    if phone_status not in PHONE_STATUSES or email_status not in EMAIL_STATUSES:
        raise ValueError("invalid contact status")

    return {
        "schema": "tinyhat_agent_contact_details_v1",
        "phone": {
            "status": phone_status,
            "phone_number": _optional_text(phone.get("phone_number"), maximum=80),
        },
        "email": {
            "status": email_status,
            "email_address": _optional_text(email.get("email_address"), maximum=320),
        },
    }


__all__ = ["contact_details"]
