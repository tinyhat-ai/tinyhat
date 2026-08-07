"""Owner-scoped shareable hat creation and discovery."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from .hat_secrets import (
    HatSecretStoreError,
    delete_hat_secret_store,
    remove_hat_secret,
    rename_hat_secret_store,
)
from .hat_repository import HatRepositoryRuntimeError, run_hat_repository
from .platform import PlatformError, build_platform_client, computer_api_path
from .secret_handoff import start_hat_credentials_handoff
from .tool_errors import tool_error_json

ACTIONS = (
    "create",
    "list",
    "get",
    "update",
    "delete",
    "put_file",
    "define_credential",
    "configure_credentials",
    "list_credentials",
    "remove_credential",
    "repository_checkout",
    "repository_status",
    "repository_sync",
    "repository_reset",
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


def hats(  # noqa: PLR0911, PLR0912, PLR0915 - one public tool dispatches bounded actions
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
                "Call tinyhat_hats with one of the supported actions in `expected`."
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
                "delete",
                "put_file",
                "define_credential",
                "configure_credentials",
                "list_credentials",
                "remove_credential",
                "repository_checkout",
                "repository_status",
                "repository_sync",
                "repository_reset",
            }
            else ""
        )
        name = _required_text(payload, "name") if action == "create" else ""
        customer_email = _required_text(payload, "customer_email") if action == "create" else ""
        update_payload: dict[str, str] | None = None
        if action == "update":
            update_payload = {"identifier": identifier}
            for field in ("public_title", "customer_email", "new_key"):
                value = str(payload.get(field) or "").strip()
                if value:
                    update_payload[field] = value
            if len(update_payload) == 1:
                return tool_error_json(
                    tool="tinyhat_hats",
                    error_name="missing_required_parameter",
                    message=(
                        "Ask the user which Hat metadata to change before calling "
                        "tinyhat_hats update."
                    ),
                    missing=["public_title, customer_email, or new_key"],
                    example_call={
                        "action": "update",
                        "identifier": "trade-show-sales",
                        "customer_email": "new-buyer@example.com",
                    },
                )
        repository_action = action.startswith("repository_")
        if repository_action:
            repository_payload: dict[str, Any] = {
                "action": action.removeprefix("repository_"),
                "identifier": identifier,
            }
            if action == "repository_sync":
                repository_payload["paths"] = payload.get("paths")
                repository_payload["message"] = _required_text(payload, "message")
            if action == "repository_reset" and payload.get("confirmed") is not True:
                return tool_error_json(
                    tool="tinyhat_hats",
                    error_name="confirmation_required",
                    message=(
                        "Only reset repository access after the user explicitly asks "
                        "to stop this Computer from renewing access to this Hat."
                    ),
                    example_call={
                        "action": "repository_reset",
                        "identifier": identifier,
                        "confirmed": True,
                    },
                )
            result = run_hat_repository(repository_payload)
        else:
            client, platform_auth = build_platform_client()
            path = computer_api_path(platform_auth, "hats/v1")
        if repository_action:
            # Repository actions are completed entirely by the public Computer
            # runtime. They must not make a second plugin-owned platform call.
            pass
        elif action == "list":
            result = client.get_json(path)
        elif action in {"get", "list_credentials"}:
            query = urlencode({"identifier": identifier})
            suffix = "credentials" if action == "list_credentials" else "detail"
            result = client.get_json(f"{path}/{suffix}?{query}")
        elif action == "update":
            assert update_payload is not None
            current_hat: dict[str, Any] | None = None
            if "new_key" in update_payload:
                query = urlencode({"identifier": identifier})
                current_hat = client.get_json(f"{path}/detail?{query}")
            result = client.post_json(
                f"{path}/update",
                update_payload,
            )
            if current_hat is not None:
                old_handle = str(current_hat.get("handle") or "").strip()
                new_handle = str(result.get("handle") or "").strip()
                if old_handle and new_handle and old_handle != new_handle:
                    try:
                        local_result = rename_hat_secret_store(
                            old_handle,
                            new_handle,
                        )
                    except HatSecretStoreError as exc:
                        result["local_store_renamed"] = False
                        result["local_store_rename_error"] = str(exc)
                    else:
                        result["local_store_renamed"] = bool(local_result["renamed"])
                        result["local_store_already_current"] = bool(
                            local_result["already_current"]
                        )
        elif action == "delete":
            if payload.get("confirmed") is not True:
                return tool_error_json(
                    tool="tinyhat_hats",
                    error_name="confirmation_required",
                    message=(
                        "Only call delete after the user explicitly asks to permanently "
                        "remove this exact Hat and its private repository."
                    ),
                    example_call={
                        "action": "delete",
                        "identifier": identifier,
                        "confirmed": True,
                    },
                )
            query = urlencode({"identifier": identifier})
            hat = client.get_json(f"{path}/detail?{query}")
            handle = str(hat.get("handle") or identifier)
            result = client.delete_json(f"{path}?{urlencode({'identifier': handle})}")
            try:
                local_result = delete_hat_secret_store(handle)
            except HatSecretStoreError as exc:
                result["local_store_removed"] = False
                result["local_cleanup_error"] = str(exc)
            else:
                result["local_store_removed"] = bool(local_result["removed"])
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
            default_bot_username = str(payload.get("default_bot_username") or "").strip()
            if default_bot_username:
                request_payload["default_bot_username"] = default_bot_username
            default_bot_display_name = str(payload.get("default_bot_display_name") or "").strip()
            if default_bot_display_name:
                request_payload["default_bot_display_name"] = default_bot_display_name
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
    except (PlatformError, HatSecretStoreError, HatRepositoryRuntimeError) as exc:
        return tool_error_json(
            tool="tinyhat_hats",
            error_name="platform_request_failed",
            message=str(exc),
        )

    if action == "repository_checkout":
        result["agent_instruction"] = (
            "Use the returned local path for repository file work. Inspect Git status "
            "and current files before editing. The clean Git remote contains no token."
        )
    elif action == "repository_status":
        result["agent_instruction"] = (
            "Report the changed paths and whether the checkout is clean. Never claim "
            "that local changes reached GitHub until repository_sync reports pushed=true."
        )
    elif action == "repository_sync":
        result["agent_instruction"] = (
            "Report the exact paths committed and the verified head SHA. The short-lived "
            "GitHub credential was used only by the Computer and was not persisted."
        )
    elif action == "repository_reset":
        result["agent_instruction"] = (
            "Report that renewal stopped and state the residual access expiry when one "
            "is returned. The existing local clone remains until the Computer is wiped."
        )
    elif action == "put_file":
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
            "Report only the metadata the user asked to change. If the handle "
            "changed, report the new canonical handle and share URL; never expose "
            "customer email unless the user explicitly asked for it. If "
            "local_store_rename_error is present, explain that the platform rename "
            "succeeded but Computer-local credentials need recovery."
        )
    elif action == "delete":
        result["agent_instruction"] = (
            "Report that the Hat and private repository were permanently deleted. "
            "Report local_store_removed honestly; if it is false because no local "
            "store existed, no plaintext value was returned or exposed."
        )
    else:
        result["agent_instruction"] = (
            "Report the canonical handle and share URL exactly as returned. Tell the "
            "user that the intended customer can verify their email on the public "
            "page and create a Telegram agent that wears this hat."
        )
    return json.dumps(result, sort_keys=True)


__all__ = ["ACTIONS", "hats"]
