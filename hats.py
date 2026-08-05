"""Owner-scoped shareable hat creation and discovery."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from .platform import PlatformError, build_platform_client, computer_api_path
from .tool_errors import tool_error_json

ACTIONS = ("create", "list", "get")


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(key)
    return value


def hats(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Create a shareable hat shell, list hats, or inspect one hat."""
    payload = args if isinstance(args, dict) else {}
    action = str(payload.get("action") or "").strip().lower()
    if action not in ACTIONS:
        return tool_error_json(
            tool="tinyhat_hats",
            error_name="invalid_parameter",
            message="Call tinyhat_hats with action='create', 'list', or 'get'.",
            expected={"action": list(ACTIONS)},
            example_call={"action": "list"},
        )

    try:
        identifier = _required_text(payload, "identifier") if action == "get" else ""
        name = _required_text(payload, "name") if action == "create" else ""
        customer_email = (
            _required_text(payload, "customer_email") if action == "create" else ""
        )
        client, platform_auth = build_platform_client()
        path = computer_api_path(platform_auth, "hats/v1")
        if action == "list":
            result = client.get_json(path)
        elif action == "get":
            query = urlencode({"identifier": identifier})
            result = client.get_json(f"{path}/detail?{query}")
        else:
            request_payload = {
                "name": name,
                "customer_email": customer_email,
            }
            key = str(payload.get("key") or "").strip()
            if key:
                request_payload["key"] = key
            default_bot_username = str(
                payload.get("default_bot_username") or ""
            ).strip()
            if default_bot_username:
                request_payload["default_bot_username"] = default_bot_username
            default_bot_display_name = str(
                payload.get("default_bot_display_name") or ""
            ).strip()
            if default_bot_display_name:
                request_payload["default_bot_display_name"] = (
                    default_bot_display_name
                )
            result = client.post_json(path, request_payload)
    except ValueError as exc:
        missing = str(exc)
        return tool_error_json(
            tool="tinyhat_hats",
            error_name="missing_required_parameter",
            message=f"Ask the user for `{missing}` before calling tinyhat_hats.",
            missing=[missing],
            example_call=(
                {
                    "action": "create",
                    "name": "Trade Show Sales",
                    "customer_email": "buyer@example.com",
                }
                if action == "create"
                else {"action": "get", "identifier": "trade-show-sales"}
            ),
        )
    except PlatformError as exc:
        return tool_error_json(
            tool="tinyhat_hats",
            error_name="platform_request_failed",
            message=str(exc),
        )

    result["agent_instruction"] = (
        "Report the canonical handle and share URL exactly as returned. Tell the "
        "user that the intended customer can verify their email on the public page "
        "and create a Telegram agent that wears this hat. The Computer is prepared "
        "only after that agent is approved."
    )
    return json.dumps(result, sort_keys=True)


__all__ = ["ACTIONS", "hats"]
