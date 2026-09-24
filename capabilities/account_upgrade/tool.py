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
    "telegram_review_url",
    "approval_expires_at",
    "status",
    "stage",
    "message",
    "requirements",
    "stripe_form_required",
    "spending_limit_cents",
    "autonomous_services_authorized",
    "autonomous_paid_services_authorized",
    "services_authorization_url",
    "reserved_limit_cents",
    "available_limit_cents",
    "provider_allowances",
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
        individual = payload.get("individual")
        country = individual.get("country") if isinstance(individual, dict) else None
        if not isinstance(country, str) or not re.fullmatch(r"[A-Za-z]{2}", country.strip()):
            return _error(
                "individual_details_required",
                "Ask only for the owner's two-letter country code or offer the private upgrade form.",
            )
    return None


def _request_failure(action: str, exc: Exception) -> str:
    known = {
        "owner_email_required": "Verify your email in your existing Tinyhat profile first. In Telegram, open Configure and your Profile. Do not sign up for another account.",
        "computer_owner_unavailable": "Tinyhat could not confirm this Computer's current owner. Check its assignment before retrying.",
        "computer_owner_changed": "Tinyhat could not confirm this Computer's current owner. Check its assignment before retrying.",
        "stripe_hosted_unavailable": "Ask the owner to open Profile (person icon) on computer.tinyhat.ai, then Upgrade your agent and Continue to finish Stripe's embedded form. Do not retry the hosted link.",
        "country_unavailable": "Stripe Projects is not available for that country. Check the country with the owner; do not substitute another country. The owner can check their Profile or contact Tinyhat support.",
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


def _review_bots() -> set[str]:
    bots = {"tinyhatbot"}
    override = runtime_env().get("TINYHAT_ACCOUNT_REVIEW_BOT_USERNAME", "").strip()
    if override:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", override):
            raise ValueError("invalid configured review bot")
        bots.add(override.lower())
    return bots


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
        for field in ("approval_url", "telegram_review_url", "revision", "approval_expires_at"):
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
        telegram_review_url = result.get("telegram_review_url")
        if telegram_review_url is not None:
            if not isinstance(telegram_review_url, str):
                raise ValueError("invalid Telegram review URL")
            link = urlsplit(telegram_review_url)
            query = parse_qs(link.query, keep_blank_values=True, strict_parsing=True)
            payload = query.get("start", [""])[0]
            if (
                link.scheme != "https" or link.hostname != "t.me"
                or link.username or link.password or link.port is not None
                or not re.fullmatch(r"/[A-Za-z][A-Za-z0-9_]{4,31}", link.path)
                or link.path[1:].lower() not in _review_bots()
                or link.fragment or query != {"start": [payload]}
                or not re.fullmatch(r"tu_[1-9][0-9]{0,17}_" + re.escape(result["revision"]), payload)
            ):
                raise ValueError("invalid Telegram review URL")
            telegram_review_url = f"https://t.me/{link.path[1:].lower()}?start={payload}"
            safe["telegram_review_url"] = telegram_review_url
        if action in {"prepare", "review_link"}:
            safe["telegram_button_sent"] = _send_review_button(url, telegram_review_url=telegram_review_url)
    return json.dumps(safe, sort_keys=True)


def _send_review_button(url: str, *, telegram_review_url: str | None = None) -> bool:
    try:
        from ...tools import _telegram_credentials, _telegram_send_message

        token, chat_id = _telegram_credentials()
        opening = (
            "Open Tinyhat, tap Start if asked, then tap its Review account upgrade button. "
            if telegram_review_url else "Open the form and sign in if asked. "
        )
        result = _telegram_send_message(
            token=token,
            chat_id=chat_id,
            text="Your account upgrade is ready to review. " + opening + "Check every detail and the terms, then approve. Ask me for corrections if needed. Setup waits for your approval.",
            reply_markup={"inline_keyboard": [[{
                "text": "Review account upgrade",
                "url": telegram_review_url or url,
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
                {
                    "individual": {"country": payload["individual"]["country"].strip().upper()},
                    "revision": payload.get("revision"),
                },
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
