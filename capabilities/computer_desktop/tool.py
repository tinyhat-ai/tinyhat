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
        or not link.startswith(("https://", "http://"))
        or ACCESS_CODE_RE.fullmatch(access_code) is None
        or not expires_at
        or payload.get("view_only") is not True
    ):
        raise ValueError("invalid desktop response")
    return {
        "schema": "tinyhat_computer_desktop_v1",
        "session_id": session_id,
        "link": link,
        "access_code": access_code,
        "expires_at": expires_at,
        "view_only": True,
        "button_label": "Open desktop",
    }


__all__ = ["computer_desktop"]
