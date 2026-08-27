"""Thin platform client for sharing this Computer's desktop with its owner."""

from __future__ import annotations

import json
import re
from typing import Any

from ...platform import PlatformError, build_platform_client, computer_api_path
from ...tool_errors import tool_error_json

SESSION_ID_RE = re.compile(r"^dsk_[A-Za-z0-9_-]{20,80}$")
ACCESS_CODE_RE = re.compile(r"^[0-9]{6}$")


def computer_desktop(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Create or reuse a short-lived owner desktop connection."""
    _ = args
    try:
        client, platform_auth = build_platform_client()
        payload = client.post_json(
            computer_api_path(platform_auth, "desktop-sessions/v1"),
            {},
        )
        result = _safe_payload(payload)
        result["telegram_button_sent"] = _send_desktop_button(result)
    except PlatformError:
        return tool_error_json(
            tool="tinyhat_computer_desktop",
            error_name="computer_desktop_unavailable",
            message="Tinyhat could not prepare this Computer's desktop right now.",
        )
    except (TypeError, ValueError):
        return tool_error_json(
            tool="tinyhat_computer_desktop",
            error_name="invalid_platform_response",
            message="Tinyhat returned an invalid desktop connection.",
        )
    return json.dumps(result, sort_keys=True)


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("invalid desktop response")
    session_id = str(payload.get("session_id") or "")
    link = str(payload.get("link") or "")
    access_code = str(payload.get("access_code") or "")
    expires_at = str(payload.get("expires_at") or "")
    if (
        SESSION_ID_RE.fullmatch(session_id) is None
        or not link.startswith("https://")
        or ACCESS_CODE_RE.fullmatch(access_code) is None
        or not expires_at
        or payload.get("view_only") is not False
    ):
        raise ValueError("invalid desktop response")
    return {
        "schema": "tinyhat_computer_desktop_v1",
        "link": link,
        "access_code": access_code,
        "expires_at": expires_at,
        "interactive": True,
        "button_label": "Open desktop",
    }


def _send_desktop_button(created: dict[str, Any]) -> bool:
    """Send the assigned owner a native Telegram Mini App button."""

    try:
        # Late import avoids a cycle through the root Hermes tool facade.
        from ...tools import (  # noqa: PLC0415
            _telegram_credentials,
            _telegram_send_message,
        )

        token, chat_id = _telegram_credentials()
        sent = _telegram_send_message(
            token=token,
            chat_id=chat_id,
            text=(
                "Your interactive Computer desktop is ready.\n\n"
                "Open it inside Telegram with the button below, or use this link "
                "in any browser:\n"
                f"{created['link']}\n\n"
                f"Access code: {created['access_code']}\n"
                f"Available until: {created['expires_at']}"
            ),
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": created["button_label"],
                            "web_app": {"url": created["link"]},
                        }
                    ]
                ]
            },
        )
        return bool(sent.get("ok"))
    except Exception:
        return False


__all__ = ["computer_desktop"]
