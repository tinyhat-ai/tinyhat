"""Owner-scoped shareable hat creation and discovery."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlencode

from .hat_repository import HatRepositoryRuntimeError, run_hat_repository
from .hat_secrets import (
    HatSecretStoreError,
    delete_hat_secret_store,
    encrypt_hat_secret_bundle_for_public_key,
    list_hat_secret_names,
    normalize_hat_handle,
    remove_hat_secret,
    rename_hat_secret_store,
)
from .hat_skill_installer import HatSkillInstallError, install_hat_skills
from .platform import PlatformError, build_platform_client, computer_api_path
from .secret_handoff import (
    SecretHandoffError,
    start_hat_credentials_handoff,
    start_hat_installation_credentials,
)
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
    "wear",
    "resume_installation",
    "list_pending_transfers",
    "complete_transfer",
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
    started_at = time.perf_counter()
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
                "wear",
                "complete_transfer",
            }
            else ""
        )
        name = _required_text(payload, "name") if action == "create" else ""
        customer_email = (
            _required_text(payload, "customer_email") if action == "create" else ""
        )
        update_payload: dict[str, Any] | None = None
        if action == "update":
            update_payload = {"identifier": identifier}
            for field in (
                "public_title",
                "customer_email",
                "default_bot_username",
                "default_bot_display_name",
                "new_key",
                "billing_mode",
                "minimum_plugin_version",
                "minimum_runtime_version",
            ):
                value = str(payload.get(field) or "").strip()
                if value:
                    update_payload[field] = value
            for field in (
                "subscription_product_id",
                "subscription_price_id",
                "monthly_price_cents",
                "trial_days",
                "discount_percent",
                "discount_duration_months",
            ):
                if payload.get(field) is not None:
                    update_payload[field] = payload[field]
            minimum_computer_type = str(
                payload.get("minimum_computer_type_key") or ""
            ).strip()
            if minimum_computer_type:
                update_payload["computer_type_key"] = minimum_computer_type
            if len(update_payload) == 1:
                return tool_error_json(
                    tool="tinyhat_hats",
                    error_name="missing_required_parameter",
                    message=(
                        "Ask the user which Hat metadata to change before calling "
                        "tinyhat_hats update."
                    ),
                    missing=["a Hat metadata field"],
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
            if action == "list_credentials":
                handle = str(result.get("handle") or identifier).strip()
                try:
                    local_names = set(list_hat_secret_names(handle)["names"])
                except (HatSecretStoreError, OSError):
                    credentials = result.get("credentials")
                    if isinstance(credentials, list):
                        for credential in credentials:
                            if isinstance(credential, dict):
                                credential.pop("has_local_value", None)
                    result["local_value_status"] = "unavailable"
                else:
                    credentials = result.get("credentials")
                    if isinstance(credentials, list):
                        for credential in credentials:
                            if not isinstance(credential, dict):
                                continue
                            name = str(credential.get("name") or "").strip().upper()
                            credential["has_local_value"] = name in local_names
                    result["local_value_status"] = "available"
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
            checkout_handles = result.get("local_checkout_handles")
            if not isinstance(checkout_handles, list):
                checkout_handles = [handle]
            checkout_handles = list(
                dict.fromkeys(
                    str(item).strip() for item in checkout_handles if str(item).strip()
                )
            )
            checkout_cleanup: list[dict[str, Any]] = []
            local_checkouts = result.get("local_checkouts")
            if not isinstance(local_checkouts, list) or not local_checkouts:
                checkout_cleanup.append(
                    {
                        "action": "delete_local",
                        "removed": False,
                        "error": (
                            "Trusted repository metadata was not returned; local "
                            "checkout deletion was skipped."
                        ),
                    }
                )
            else:
                for checkout in local_checkouts:
                    if not isinstance(checkout, dict):
                        checkout_cleanup.append(
                            {
                                "action": "delete_local",
                                "removed": False,
                                "error": "Trusted repository metadata was invalid.",
                            }
                        )
                        continue
                    checkout_handle = str(checkout.get("handle") or "").strip()
                    repository = {
                        "owner": str(checkout.get("repository_owner") or "").strip(),
                        "name": str(checkout.get("repository_name") or "").strip(),
                        "url": str(checkout.get("repository_url") or "").strip(),
                    }
                    try:
                        checkout_cleanup.append(
                            run_hat_repository(
                                {
                                    "action": "delete_local",
                                    "identifier": checkout_handle,
                                    "repository": repository,
                                }
                            )
                        )
                    except HatRepositoryRuntimeError as exc:
                        checkout_cleanup.append(
                            {
                                "action": "delete_local",
                                "hat_handle": checkout_handle,
                                "removed": False,
                                "error": str(exc),
                            }
                        )
            result["local_checkout_cleanup"] = checkout_cleanup
            result["local_checkout_cleanup_complete"] = all(
                "error" not in item for item in checkout_cleanup
            )
            secret_store_removed = False
            secret_cleanup_errors: list[str] = []
            for checkout_handle in checkout_handles:
                try:
                    local_result = delete_hat_secret_store(checkout_handle)
                except HatSecretStoreError as exc:
                    secret_cleanup_errors.append(str(exc))
                else:
                    secret_store_removed = (
                        bool(local_result["removed"]) or secret_store_removed
                    )
            result["local_store_removed"] = secret_store_removed
            if secret_cleanup_errors:
                result["local_cleanup_error"] = "; ".join(secret_cleanup_errors)
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
        elif action in {"wear", "resume_installation"}:
            result = _wear_hat(
                client=client,
                platform_auth=platform_auth,
                identifier=identifier if action == "wear" else None,
            )
        elif action == "list_pending_transfers":
            result = client.get_json(f"{path}/credential-transfers")
        elif action == "complete_transfer":
            result = _complete_credential_transfer(
                client=client,
                path=path,
                identifier=identifier,
                handoff_id=str(payload.get("handoff_id") or "").strip(),
            )
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
                request_payload["default_bot_display_name"] = default_bot_display_name
            for field in (
                "billing_mode",
                "subscription_product_id",
                "subscription_price_id",
                "minimum_plugin_version",
                "minimum_runtime_version",
                "monthly_price_cents",
                "trial_days",
                "discount_percent",
                "discount_duration_months",
            ):
                if payload.get(field) is not None and payload.get(field) != "":
                    request_payload[field] = payload[field]
            minimum_computer_type = str(
                payload.get("minimum_computer_type_key") or ""
            ).strip()
            if minimum_computer_type:
                request_payload["computer_type_key"] = minimum_computer_type
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
    except (
        PlatformError,
        HatSecretStoreError,
        HatRepositoryRuntimeError,
        HatSkillInstallError,
        SecretHandoffError,
    ) as exc:
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
            "Report credential names and safe metadata only. When local_value_status "
            "is available, has_local_value is the authoritative Computer-local saved "
            "state. Secret values remain local and are never returned by Tinyhat."
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
            "Report local_store_removed and local_checkout_cleanup_complete honestly. "
            "No plaintext value was returned or exposed."
        )
    elif action in {"wear", "resume_installation"}:
        result["agent_instruction"] = (
            "Send onboarding_message as the immediate progress update when it is "
            "present. If payment_required is true, send the checkout URL and wait for "
            "the user to complete it before resuming. If installation_started is "
            "true, explain that the skills are loaded and any private credentials are "
            "moving directly between Computers as ciphertext. A status of none means "
            "this Computer has no Hat to install and needs no user-facing warning. "
            "Never claim the Hat is fully ready until status=active or the final "
            "platform notice arrives."
        )
    elif action == "list_pending_transfers":
        result["agent_instruction"] = (
            "These are value-blind requests for Hats created on this Computer. "
            "Complete each requested transfer without asking for secret values."
        )
    elif action == "complete_transfer":
        result["agent_instruction"] = (
            "Report only the Hat handle and credential count. The plaintext stayed "
            "on this Computer and only ciphertext was relayed to the consumer."
        )
    else:
        result["agent_instruction"] = (
            "Report the canonical handle and share URL exactly as returned. Tell the "
            "user that the intended customer can verify their email on the public "
            "page and create a Telegram agent that wears this hat."
        )
    result_without_telemetry = json.dumps(result, sort_keys=True, separators=(",", ":"))
    input_shape = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    result["operation_telemetry"] = {
        "action": action,
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000),
        "estimated_tool_input_tokens": max(1, (len(input_shape) + 3) // 4),
        "estimated_tool_output_tokens": max(
            1, (len(result_without_telemetry) + 3) // 4
        ),
        "agent_run_token_usage_source": "Hermes agent run trace",
    }
    return json.dumps(result, sort_keys=True)


def _wear_hat(
    *,
    client: Any,
    platform_auth: str,
    identifier: str | None,
) -> dict[str, Any]:
    base = computer_api_path(platform_auth, "hats/v1")
    installation = (
        client.post_json(f"{base}/wear", {"identifier": identifier})
        if identifier
        else client.get_json(f"{base}/installation")
    )
    if not installation:
        return {
            "status": "none",
            "installation_started": False,
            "onboarding_message": None,
        }
    if installation.get("payment_required") or installation.get("status") in {
        "payment_pending",
        "assignment_pending",
    }:
        return installation
    if installation.get("status") == "active":
        installation["installation_started"] = False
        return installation
    handle = normalize_hat_handle(str(installation.get("hat_handle") or ""))
    repository = run_hat_repository({"action": "checkout", "identifier": handle})
    skills = install_hat_skills(handle, str(repository.get("path") or ""))
    installation = client.post_json(
        f"{base}/installation/skills",
        {
            "installation_id": str(installation.get("installation_id") or ""),
            "head_sha": str(repository.get("head_sha") or ""),
        },
    )
    transfer = start_hat_installation_credentials(
        installation_id=str(installation.get("installation_id") or ""),
        hat_handle=handle,
    )
    installation.update(
        {
            "installation_started": True,
            "repository": {
                "path": repository.get("path"),
                "head_sha": repository.get("head_sha"),
            },
            "skills": skills,
            "credential_transfer": transfer,
        }
    )
    if transfer.get("credential_count") == 0:
        installation["status"] = "active"
    return installation


def _complete_credential_transfer(
    *,
    client: Any,
    path: str,
    identifier: str,
    handoff_id: str,
) -> dict[str, Any]:
    listed = client.get_json(f"{path}/credential-transfers")
    items = listed.get("items") if isinstance(listed, dict) else None
    if not isinstance(items, list):
        raise PlatformError("The platform returned invalid Hat transfer metadata.")
    matches = [
        item
        for item in items
        if isinstance(item, dict)
        and (not handoff_id or str(item.get("handoff_id") or "") == handoff_id)
        and (not identifier or str(item.get("hat_handle") or "") == identifier)
    ]
    if len(matches) != 1:
        raise PlatformError(
            "Select one exact pending Hat transfer by handoff id or Hat handle."
        )
    transfer = matches[0]
    credentials = transfer.get("credentials")
    if not isinstance(credentials, list):
        raise PlatformError("The transfer credential metadata is invalid.")
    names = [
        str(item.get("name") or "")
        for item in credentials
        if isinstance(item, dict)
    ]
    encrypted = encrypt_hat_secret_bundle_for_public_key(
        str(transfer.get("hat_handle") or ""),
        public_key_pem=str(transfer.get("public_key_pem") or ""),
        expected_names=names,
    )
    submitted = client.post_json(
        f"{path}/credential-transfers/{transfer['handoff_id']}",
        {"ciphertext_payload": encrypted["ciphertext_payload"]},
    )
    return {
        "handoff_id": str(transfer["handoff_id"]),
        "hat_handle": str(transfer["hat_handle"]),
        "credential_count": len(names),
        "submitted": str(submitted.get("status") or "") == "submitted",
        "value_available": False,
    }


__all__ = ["ACTIONS", "hats"]
