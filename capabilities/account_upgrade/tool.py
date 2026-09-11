"""Thin client for assignment-scoped account upgrades; no credentials in output."""

from __future__ import annotations

import json
import re
from http.client import HTTPException
from typing import Any
from urllib.parse import parse_qs, urlparse, urlsplit

from ...platform import PlatformError, build_platform_client, runtime_env
from ...tool_errors import tool_error_json

BASE = "/hapi/v2/computers/me/account"
STATUS_FIELDS = {
    "available",
    "revision",
    "approval_url",
    "mini_app_url",
    "approval_expires_at",
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


def _validate(payload: dict[str, Any], action: str) -> str | None:
    allowed = {"action", "individual", "revision"} if action == "prepare" else {"action"}
    if set(payload) - allowed:
        return _error(
            "invalid_arguments",
            "Prepare details only. Final approval belongs on the owner's review page; do not supply consent or account identifiers.",
        )
    if action == "prepare":
        revision = payload.get("revision")
        if revision is not None and (
            not isinstance(revision, str) or not re.fullmatch(r"thur_[A-Za-z0-9_-]{32}", revision)
        ):
            return _error(
                "invalid_arguments",
                "Use the current revision returned by status when correcting a draft.",
            )
        if not isinstance(payload.get("individual"), dict):
            return _error(
                "individual_details_required",
                "Ask for the individual's accurate details or offer the private upgrade form.",
            )
    return None


def _request_failure(action: str, exc: Exception) -> str:
    known = {
        "owner_email_required": "Verify your email in your existing Tinyhat profile first. In Telegram, open Configure and your Profile. Do not sign up for another account.",
        "computer_owner_unavailable": "Tinyhat could not confirm this Computer's current owner. Check its assignment before retrying.",
        "computer_owner_changed": "Tinyhat could not confirm this Computer's current owner. Check its assignment before retrying.",
    }
    response = (
        exc.response if isinstance(exc, PlatformError) and isinstance(exc.response, dict) else {}
    )
    error = response.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, str) and code in known:
        return _error(code, known[code])
    status = exc.status_code if isinstance(exc, PlatformError) else None
    statuses = {
        429: (
            "account_upgrade_rate_limited",
            "Tinyhat is limiting requests. Wait at least one minute, then check status; do not resubmit now.",
        ),
        409: (
            "account_upgrade_conflict",
            "Check status for the latest revision. Correct only an unapproved draft, then ask the owner to review again. Approved requests need support for changes.",
        ),
        422: (
            "invalid_request",
            "Check the individual's details and the current terms version. Never guess missing information or approval.",
        ),
        401: (
            "computer_authentication_required",
            "This Computer could not authenticate. Do not use another user's credentials.",
        ),
        403: (
            "computer_authentication_required",
            "This Computer could not authenticate. Do not use another user's credentials.",
        ),
    }
    if status in statuses:
        return _error(*statuses[status])
    if action == "prepare":
        return _error(
            "upgrade_submission_uncertain",
            "The upgrade was not confirmed. Check status before retrying the identical request; do not create another account.",
        )
    return _error(
        "account_upgrade_unavailable",
        "Tinyhat could not confirm the upgrade. Check status later before proceeding; do not create another account.",
    )


def _verification_link(result: dict[str, Any]) -> str:
    url = result.get("url", "")
    if not isinstance(url, str):
        raise ValueError("invalid verification URL")
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


def _review_hosts(base_url: str) -> set[str | None]:
    hosts = {"computer.tinyhat.ai", urlsplit(base_url).hostname}
    # Operator/runtime configuration, never a tool argument or returned profile.
    origin = runtime_env().get("TINYHAT_ACCOUNT_REVIEW_ORIGIN", "").strip()
    if origin:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid configured review origin")
        hosts.add(parsed.hostname)
    return hosts


def _safe_result(action: str, result: dict[str, Any], *, base_url: str = "") -> str:
    if action == "verification_link":
        return _verification_link(result)
    if result.get("status") not in {
        "not_started",
        "awaiting_approval",
        "pending",
        "needs_information",
        "ready",
        "setup_required",
        "recovery_required",
    }:
        raise ValueError("invalid status")
    safe = {key: value for key, value in result.items() if key in STATUS_FIELDS}
    if result.get("status") != "awaiting_approval":
        for field in ("approval_url", "mini_app_url", "revision", "approval_expires_at"):
            safe.pop(field, None)
    if result.get("status") == "awaiting_approval":
        url = result.get("approval_url")
        if not isinstance(url, str):
            raise ValueError("missing review URL")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _review_hosts(base_url)
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or parsed.path != "/tinyhat/account/upgrade"
            or parsed.fragment
            or not isinstance(result.get("revision"), str)
            or not re.fullmatch(r"thur_[A-Za-z0-9_-]{32}", result["revision"])
            or parse_qs(parsed.query) != {"review": [result["revision"]]}
        ):
            raise ValueError("invalid review URL")
        mini_app_url = result.get("mini_app_url")
        if mini_app_url is not None:
            mini = urlsplit(mini_app_url)
            if (
                mini.scheme != "https"
                or mini.hostname not in (_review_hosts(base_url) | {"use.tinyloop.co"})
                or mini.username or mini.password or mini.port not in {None, 443}
                or not re.fullmatch(r"/tinyhat/miniapp/agents/[A-Za-z0-9_-]+/account/upgrade", mini.path)
                or mini.fragment
                or parse_qs(mini.query) != {"review": [result["revision"]]}
            ):
                raise ValueError("invalid Mini App review URL")
        if action in {"prepare", "review_link"}:
            safe["telegram_button_sent"] = _send_review_button(url, mini_app_url=mini_app_url)
    return json.dumps(safe, sort_keys=True)


def _send_review_button(url: str, *, mini_app_url: str | None = None) -> bool:
    try:
        from ...tools import _telegram_credentials, _telegram_send_message

        token, chat_id = _telegram_credentials()
        result = _telegram_send_message(
            token=token,
            chat_id=chat_id,
            text="Your account upgrade is ready to review. Open the form, check every detail and the terms, then approve. Ask me for corrections if needed. Setup waits for your approval.",
            reply_markup={"inline_keyboard": [[{
                "text": "Review account upgrade",
                **({"web_app": {"url": mini_app_url}} if mini_app_url else {"url": url}),
            }]]},
        )
        return bool(result.get("ok"))
    except Exception:
        return False


def account_upgrade(args: dict[str, Any] | None = None, **_: Any) -> str:
    payload = args if isinstance(args, dict) else {}
    action = payload.get("action", "status")
    if not isinstance(action, str) or action not in {
        "status",
        "prepare",
        "review_link",
        "continue",
        "verification_link",
    }:
        return _error(
            "invalid_action", "Use status, prepare, review_link, continue, or verification_link."
        )
    invalid = _validate(payload, action)
    if invalid:
        return invalid
    try:
        client, authentication = build_platform_client(timeout_seconds=45)
        if authentication != "gcloud":
            return _error(
                "computer_identity_required",
                "Use this tool from the assigned Tinyhat cloud Computer.",
            )
        if action in {"status", "review_link"}:
            result = client.get_json(f"{BASE}/upgrade")
        elif action == "prepare":
            result = client.post_json(
                f"{BASE}/upgrade",
                {"individual": payload["individual"], "revision": payload.get("revision")},
            )
        else:
            suffix = "verification-link" if action == "verification_link" else "upgrade/continue"
            result = client.post_json(f"{BASE}/{suffix}", {})
        return _safe_result(action, result, base_url=client.base_url)
    except (PlatformError, OSError, HTTPException) as exc:
        # A response may be lost after acceptance. Never echo or retry a write.
        return _request_failure(action, exc)
    except (TypeError, ValueError, KeyError):
        return _error(
            "invalid_platform_response",
            "Tinyhat could not confirm the upgrade. Check status before proceeding.",
        )
