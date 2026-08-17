"""Value-blind credential discovery and removal confirmation tool."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode

from .platform import PlatformError, build_platform_client, computer_api_path
from .tool_errors import tool_error_json

ACTIONS = ("list", "remove")


def _credential_list(query: str | None = None) -> dict[str, Any]:
    client, platform_auth = build_platform_client()
    path = computer_api_path(platform_auth, "private-credentials/v1")
    clean_query = " ".join(str(query or "").split())
    if clean_query:
        path = f"{path}?{urlencode({'q': clean_query})}"
    return client.get_json(path)


def _select_handoff_id(payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    handoff_id = str(payload.get("handoff_id") or "").strip()
    if handoff_id:
        return handoff_id, {}
    name = str(payload.get("name") or "").strip().upper()
    if not name:
        return None, {
            "error": "missing_selector",
            "message": "Use handoff_id from list, or provide the exact credential name.",
        }
    listed = _credential_list(name)
    credentials = listed.get("credentials")
    candidates = credentials if isinstance(credentials, list) else []
    exact = [
        item
        for item in candidates
        if isinstance(item, dict) and str(item.get("name") or "").strip().upper() == name
    ]
    if len(exact) == 1:
        selected = str(exact[0].get("handoff_id") or "").strip()
        if selected:
            return selected, {}
    return None, {
        "error": "credential_not_unique",
        "message": (
            "No unique current credential matched that name. Show the related "
            "credentials and ask the user which one they mean."
        ),
        "credentials": candidates,
    }


def credentials(args: dict[str, Any] | None = None, **_: Any) -> str:
    """List safe metadata or send a platform-owned Telegram removal prompt."""
    payload = args if isinstance(args, dict) else {}
    action = str(payload.get("action") or "").strip().lower()
    if action not in ACTIONS:
        return tool_error_json(
            tool="tinyhat_credentials",
            error_name="invalid_parameter",
            message="Call tinyhat_credentials with action='list' or action='remove'.",
            expected={"action": list(ACTIONS)},
            example_call={"action": "list", "query": "search API"},
        )
    try:
        if action == "list":
            result = _credential_list(str(payload.get("query") or "").strip() or None)
            result["agent_instruction"] = (
                "Use handoff_id only as an opaque selector. Never claim or infer a "
                "credential value; the platform does not have it."
            )
            return json.dumps(result, sort_keys=True)

        handoff_id, selection_error = _select_handoff_id(payload)
        if handoff_id is None:
            return json.dumps(
                {
                    "schema": "tinyhat_private_credential_removal_start_v1",
                    "status": "selection_required",
                    **selection_error,
                },
                sort_keys=True,
            )
        client, platform_auth = build_platform_client()
        result = client.post_json(
            computer_api_path(
                platform_auth,
                f"private-credentials/v1/{quote(handoff_id, safe='')}/removal-requests",
            ),
            {},
        )
    except PlatformError as exc:
        return tool_error_json(
            tool="tinyhat_credentials",
            error_name="platform_request_failed",
            message=str(exc),
        )
    result.update(
        {
            "chat_response_required": False,
            "agent_instruction": (
                "The platform sent the expiring Telegram confirmation. Do not ask "
                "for text confirmation, expose a URL, or send a duplicate reply."
            ),
        }
    )
    return json.dumps(result, sort_keys=True)
