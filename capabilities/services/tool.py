"""Machine-identity client for reviewed, Computer-scoped Stripe Projects APIs."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, urlsplit

from ...platform import PlatformError, build_platform_client
from ...tool_errors import tool_error_json
from ..account_upgrade.tool import _review_hosts

BASE = "/hapi/v2/computers/me/services"
MAX_PAGE_URL = 1600
HTTP_SERVER_ERROR = 500
READS = {
    "status": "/project",
    "catalog_providers": "/catalog/providers",
    "catalog_services": "/catalog/services",
    "connections": "/provider-connections",
    "resources": "/resources",
}
WRITES = {
    "create_project": "/project",
    "sync_project": "/project/sync",
}
INTENT_ACTIONS = {
    "reserve_provider_allowance",
    "connect_provider",
    "create_resource",
    "link_resource",
    "update_resource",
    "remove_resource",
    "unlink_resource",
    "rotate_resource",
    "unlink_provider_connection",
}
PREPARE_FIELDS = {
    "action",
    "provider",
    "service_ref",
    "resource_id",
    "name",
    "configuration",
    "environment",
    "connection_id",
    "limit_cents",
}


def _error(code: str, message: str) -> str:
    return tool_error_json(tool="tinyhat_services", error_name=code, message=message)


def _identifier(value: Any) -> str | None:
    return (
        value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{8,160}", value) else None
    )


def _review_url(url: Any, base_url: str) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    return (
        parsed.scheme in {"https", "http"}
        and (parsed.scheme == "https" or parsed.hostname in {"localhost", "127.0.0.1"})
        and parsed.hostname in _review_hosts(base_url)
        and not parsed.username
        and not parsed.password
        and re.fullmatch(
            r"/tinyhat/computers/(?:cmp_[A-Za-z0-9_-]{32}|computer_[1-9][0-9]{0,18})/services/review/[a-f0-9-]{36}",
            parsed.path,
        )
        is not None
        and not parsed.query
        and not parsed.fragment
    )


def _send_service_review_button(url: str) -> bool:
    try:
        from ...tools import _telegram_credentials, _telegram_send_message  # noqa: PLC0415

        token, chat_id = _telegram_credentials()
        result = _telegram_send_message(
            token=token,
            chat_id=chat_id,
            text="A service change is ready for your review. Check the details before approving.",
            reply_markup={"inline_keyboard": [[{"text": "Review service", "url": url}]]},
        )
        return bool(result.get("ok"))
    except Exception:
        return False


def services(args: dict[str, Any] | None = None, **_: Any) -> str:  # noqa: PLR0911, PLR0912, PLR0915
    payload = args if isinstance(args, dict) else {}
    action = payload.get("action")
    if not isinstance(action, str) or action not in {
        *READS,
        *WRITES,
        "resource",
        "connection_request",
        "prepare",
        "intent",
        "execute",
    }:
        return _error("invalid_action", "Choose a documented service action.")
    allowed = {"action"}
    if action == "prepare":
        allowed.add("request")
    elif action in {"resource"}:
        allowed.add("resource_id")
    elif action == "connection_request":
        allowed.add("request_id")
    elif action in {"intent", "execute"}:
        allowed.add("intent_id")
    elif action in {"catalog_services", "catalog_providers", "connections", "resources"}:
        allowed.update({"page_url", "provider_name"})
    if set(payload) - allowed:
        return _error(
            "invalid_arguments", "Do not supply account, Computer, or Stripe key identifiers."
        )
    if action == "prepare":
        request = payload.get("request")
        if (
            not isinstance(request, dict)
            or set(request) - PREPARE_FIELDS
            or not isinstance(request.get("action"), str)
            or request["action"] not in INTENT_ACTIONS
        ):
            return _error(
                "invalid_arguments", "Choose a supported service action and its exact settings."
            )
    elif action == "resource" and not _identifier(payload.get("resource_id")):
        return _error("invalid_arguments", "Choose a Resource ID returned by this Computer.")
    elif action == "connection_request" and not _identifier(payload.get("request_id")):
        return _error(
            "invalid_arguments", "Choose a connection request ID returned by this Computer."
        )
    elif action in {"intent", "execute"} and not (
        isinstance(payload.get("intent_id"), str)
        and re.fullmatch(r"[a-f0-9-]{36}", payload["intent_id"])
    ):
        return _error("invalid_arguments", "Use the request ID returned by prepare.")
    try:
        client, authentication = build_platform_client(timeout_seconds=45)
        if authentication != "gcloud":
            return _error(
                "computer_identity_required", "Use this tool on the assigned Tinyhat Computer."
            )
        if action in READS:
            path = BASE + READS[action]
            params = []
            for key in ("provider_name", "page_url"):
                value = payload.get(key)
                if value is not None:
                    if not isinstance(value, str) or not value or len(value) > MAX_PAGE_URL:
                        return _error("invalid_arguments", "Invalid catalog or page input.")
                    params.append(f"{key}={quote(value, safe='')}")
            if params:
                path += "?" + "&".join(params)
            result = client.get_json(path)
        elif action in WRITES:
            result = client.post_json(BASE + WRITES[action], {})
            if action == "create_project" and not _review_url(
                result.get("review_url"), client.base_url
            ):
                return _error(
                    "invalid_platform_response", "Tinyhat returned an invalid review link."
                )
        elif action == "resource":
            resource_id = payload["resource_id"]
            result = client.get_json(f"{BASE}/resources/{resource_id}")
        elif action == "connection_request":
            result = client.get_json(f"{BASE}/provider-connection-requests/{payload['request_id']}")
        elif action == "prepare":
            request = payload["request"]
            result = client.post_json(f"{BASE}/intents", request)
            if not _review_url(result.get("review_url"), client.base_url):
                return _error(
                    "invalid_platform_response", "Tinyhat returned an invalid review link."
                )
        else:
            intent_id = payload["intent_id"]
            path = f"{BASE}/intents/{intent_id}"
            result = (
                client.post_json(path + "/execute", {})
                if action == "execute"
                else client.get_json(path)
            )
        if action in {"prepare", "create_project"} and isinstance(result.get("review_url"), str):
            result["telegram_button_sent"] = _send_service_review_button(result["review_url"])
        return json.dumps(result, sort_keys=True)
    except PlatformError as exc:
        uncertain = action in {*WRITES, "execute"} and (
            exc.status_code is None or exc.status_code >= HTTP_SERVER_ERROR
        )
        code = "service_request_uncertain" if uncertain else "service_unavailable"
        message = (
            "The outcome is uncertain. Check its status before retrying this write."
            if uncertain
            else "Tinyhat could not complete this request."
        )
        if isinstance(exc.response, dict):
            error = exc.response.get("error")
            if isinstance(error, dict) and isinstance(error.get("code"), str):
                code = error["code"]
                if isinstance(error.get("message"), str):
                    message = error["message"][:400]
        return _error(code, message)
    except (OSError, TypeError, ValueError):
        return _error(
            "service_unavailable",
            "Tinyhat could not confirm this service request. Check its status.",
        )
