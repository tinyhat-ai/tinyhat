"""Owner-scoped shareable hat creation and discovery."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from .hat_secrets import HatSecretStoreError, remove_hat_secret
from .platform import PlatformError, build_platform_client, computer_api_path
from .secret_handoff import start_hat_credentials_handoff
from .tool_errors import tool_error_json

ACTIONS = (
    "create",
    "list",
    "get",
    "update",
    "put_file",
    "define_credential",
    "configure_credentials",
    "list_credentials",
    "remove_credential",
)


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(key)
    return value


def _required_content(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "")
    if not value.strip():
        raise ValueError(key)
    return value


def hats(  # noqa: PLR0912, PLR0915 - one public tool dispatches bounded actions
    args: dict[str, Any] | None = None, **_: Any
) -> str:
    """Create, inspect, or modify one owner-scoped shareable Hat."""
    payload = args if isinstance(args, dict) else {}
    action = str(payload.get("action") or "").strip().lower()
    if action not in ACTIONS:
        return tool_error_json(
            tool="tinyhat_hats",
            error_name="invalid_parameter",
            message=(
                "Call tinyhat_hats with a supported create, list, get, update, "
                "put_file, define_credential, configure_credentials, "
                "list_credentials, or remove_credential action."
            ),
            expected={"action": list(ACTIONS)},
            example_call={"action": "list"},
        )

    try:
        identifier = (
            _required_text(payload, "identifier")
            if action
            in {
                "get",
                "update",
                "put_file",
                "define_credential",
                "configure_credentials",
                "list_credentials",
                "remove_credential",
            }
            else ""
        )
        name = _required_text(payload, "name") if action == "create" else ""
        customer_email = _required_text(payload, "customer_email") if action == "create" else ""
        client, platform_auth = build_platform_client()
        path = computer_api_path(platform_auth, "hats/v1")
        if action == "list":
            result = client.get_json(path)
        elif action in {"get", "list_credentials"}:
            query = urlencode({"identifier": identifier})
            suffix = "credentials" if action == "list_credentials" else "detail"
            result = client.get_json(f"{path}/{suffix}?{query}")
        elif action == "update":
            result = client.post_json(
                f"{path}/update",
                {
                    "identifier": identifier,
                    "public_title": _required_text(payload, "public_title"),
                },
            )
        elif action == "put_file":
            result = client.post_json(
                f"{path}/files",
                {
                    "identifier": identifier,
                    "path": _required_text(payload, "path"),
                    "content": _required_content(payload, "content"),
                },
            )
        elif action == "define_credential":
            result = client.post_json(
                f"{path}/credentials/define",
                {
                    "identifier": identifier,
                    "name": _required_text(payload, "credential_name").upper(),
                    "description": _required_text(payload, "description"),
                },
            )
        elif action == "configure_credentials":
            return start_hat_credentials_handoff(identifier)
        elif action == "remove_credential":
            if payload.get("confirmed") is not True:
                return tool_error_json(
                    tool="tinyhat_hats",
                    error_name="confirmation_required",
                    message=(
                        "Only call remove_credential after the user explicitly asks "
                        "to remove this exact credential from this exact Hat."
                    ),
                    example_call={
                        "action": "remove_credential",
                        "identifier": identifier,
                        "credential_name": "EXA_API_KEY",
                        "confirmed": True,
                    },
                )
            credential_name = _required_text(payload, "credential_name").upper()
            query = urlencode({"identifier": identifier})
            hat = client.get_json(f"{path}/detail?{query}")
            local_result = remove_hat_secret(
                str(hat.get("handle") or ""),
                credential_name,
            )
            result = client.post_json(
                f"{path}/credentials/remove",
                {
                    "identifier": str(hat.get("handle") or identifier),
                    "name": credential_name,
                },
            )
            result["local_value_removed"] = bool(local_result["removed"])
        else:  # create
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
    except (PlatformError, HatSecretStoreError) as exc:
        return tool_error_json(
            tool="tinyhat_hats",
            error_name="platform_request_failed",
            message=str(exc),
        )

    if action == "put_file":
        result["agent_instruction"] = (
            "Report whether the file was created or updated and name its repo path. "
            "Never imply that a secret value belongs in a Hat repo file."
        )
    elif action == "define_credential":
        result["agent_instruction"] = (
            "The credential name and description are defined without a value. "
            "After defining every requested credential, call configure_credentials "
            "once so the user receives one encrypted form for all values."
        )
    elif action in {"list_credentials", "remove_credential"}:
        result["agent_instruction"] = (
            "Report credential names and safe metadata only. Secret values remain in "
            "the Computer-local Hat store and are never returned by Tinyhat."
        )
    elif action == "update":
        result["agent_instruction"] = (
            "Report the updated public title and unchanged canonical handle."
        )
    else:
        result["agent_instruction"] = (
            "Report the canonical handle and share URL exactly as returned. Tell the "
            "user that the intended customer can verify their email on the public "
            "page and create a Telegram agent that wears this hat."
        )
    return json.dumps(result, sort_keys=True)


__all__ = ["ACTIONS", "hats"]
