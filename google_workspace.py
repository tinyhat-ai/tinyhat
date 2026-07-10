"""Google Workspace connection tool for Tinyhat-managed Computers.

The platform owns the Google OAuth web client and callback. This plugin owns
the Computer-side keypair, one-time handoff worker, and local credential file.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import parse

from .platform import PlatformClient, build_platform_client, computer_api_path
from .secret_handoff import KEY_ALGORITHM, _decrypt_ciphertext, _generate_key_pair
from .tool_errors import tool_error_json

GOOGLE_WORKSPACE_ACTIONS = ("connect", "status", "disconnect")
GOOGLE_WORKSPACE_CREDENTIAL_SCHEMA = "tinyhat_google_workspace_credentials_v1"
GOOGLE_WORKSPACE_REFRESH_SCHEMA = "tinyhat_google_workspace_refresh_v1"
GOOGLE_WORKSPACE_DISCONNECT_INTENT_SCHEMA = "tinyhat_google_workspace_disconnect_intent_v1"
GOOGLE_WORKSPACE_DISCONNECT_WORKER_STATE_SCHEMA = (
    "tinyhat_google_workspace_disconnect_worker_state_v1"
)
GOOGLE_WORKSPACE_DISCONNECT_WORKER_READY_SCHEMA = (
    "tinyhat_google_workspace_disconnect_worker_ready_v1"
)
GOOGLE_WORKSPACE_DISCONNECT_COMPLETION_RECEIPT_SCHEMA = (
    "tinyhat_google_workspace_disconnect_completion_receipt_v1"
)
GOOGLE_WORKSPACE_API_SUFFIX = "google-workspace-oauth/v1"
GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX = f"{GOOGLE_WORKSPACE_API_SUFFIX}/disconnect-intents"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_WORKSPACE_PROFILE_READONLY = "workspace_readonly"
GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND = "gmail_send"
GOOGLE_WORKSPACE_PROFILES = (
    GOOGLE_WORKSPACE_PROFILE_READONLY,
    GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND,
)
GOOGLE_READONLY_CAPABILITY_BUNDLE = "google_workspace_readonly_v1"
GOOGLE_GMAIL_SEND_CAPABILITY_BUNDLE = "google_workspace_gmail_send_v1"
GOOGLE_REQUESTED_SERVICES = ("identity", "gmail", "calendar", "drive")
GOOGLE_READONLY_SCOPES = (
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
)
GOOGLE_GMAIL_SEND_SCOPES = (
    *GOOGLE_READONLY_SCOPES,
    "https://www.googleapis.com/auth/gmail.send",
)
# Backward-compatible names for callers that only need the default profile.
GOOGLE_CAPABILITY_BUNDLE = GOOGLE_READONLY_CAPABILITY_BUNDLE
GOOGLE_REQUESTED_SCOPES = GOOGLE_READONLY_SCOPES
GOOGLE_AUTHORIZATION_HOST = "accounts.google.com"
GOOGLE_AUTHORIZATION_PATH = "/o/oauth2/v2/auth"
DEFAULT_EXPIRES_IN_SECONDS = 600
DISCONNECT_WORKER_READY_TIMEOUT_SECONDS = 15.0
DISCONNECT_WORKER_READY_POLL_SECONDS = 0.05
DISCONNECT_COMPLETION_RETRY_SECONDS = 60 * 60
DISCONNECT_COMPLETION_MAX_RETRY_DELAY_SECONDS = 30.0
DISCONNECT_AUTO_RESUME_LIMIT = 8
DISCONNECT_ORPHAN_SWEEP_GRACE_SECONDS = 5 * 60
DISCONNECT_ORPHAN_SWEEP_SCAN_LIMIT = 32
DISCONNECT_ORPHAN_SWEEP_DELETE_LIMIT = 8
CONTEXT_ASSIGNMENT_CHECK_TTL_SECONDS = 30.0
CONTEXT_ASSIGNMENT_CHECK_TIMEOUT_SECONDS = 2
AUTHORIZATION_URL_MAX_LENGTH = 16_384
PUBLIC_CLIENT_ID_MAX_LENGTH = 512
GOOGLE_TOKEN_VALUE_MAX_LENGTH = 16_384
GOOGLE_TOKEN_EXPIRY_MAX_LENGTH = 64
OWNER_ONLY_FILE_MODE = 0o600
HANDOFF_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
DISCONNECT_OWNER_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
DISCONNECT_GENERATION_RE = re.compile(r"^[0-9a-f]{64}$")
STATE_DIR = Path.home() / ".tinyhat" / "google-workspace"
CREDENTIALS_PATH = STATE_DIR / "credentials.json"
HANDOFFS_DIR = STATE_DIR / "handoffs"
ACTIVE_HANDOFF_PATH = STATE_DIR / "active-handoff.json"
DISCONNECTS_DIR = STATE_DIR / "disconnects"
ACTIVE_DISCONNECT_PATH = STATE_DIR / "active-disconnect.json"
LIFECYCLE_LOCK_PATH = STATE_DIR / "lifecycle.lock"
WORKER_SYSTEMD_ENV_KEYS = (
    "HOME",
    "PATH",
    "PYTHONPATH",
    "TINYHAT_PLATFORM_URL",
    "TINYHAT_COMPUTER_TOKEN_AUDIENCE",
)
_context_assignment_check_cache: dict[
    str, tuple[tuple[int, int, int, int, str], float]
] = {}
_context_assignment_check_cache_lock = threading.Lock()


class GoogleWorkspaceError(RuntimeError):
    """A Google Workspace connection step failed safely."""


@dataclass(frozen=True)
class GoogleWorkspaceProfile:
    """One plugin-owned, platform-allowlisted OAuth capability profile."""

    name: str
    capability_bundle: str
    services: tuple[str, ...]
    scopes: tuple[str, ...]
    access_label: str


GOOGLE_PROFILE_CONFIGS = {
    GOOGLE_WORKSPACE_PROFILE_READONLY: GoogleWorkspaceProfile(
        name=GOOGLE_WORKSPACE_PROFILE_READONLY,
        capability_bundle=GOOGLE_READONLY_CAPABILITY_BUNDLE,
        services=GOOGLE_REQUESTED_SERVICES,
        scopes=GOOGLE_READONLY_SCOPES,
        access_label="read-only Gmail, Calendar, and Drive access",
    ),
    GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND: GoogleWorkspaceProfile(
        name=GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND,
        capability_bundle=GOOGLE_GMAIL_SEND_CAPABILITY_BUNDLE,
        services=GOOGLE_REQUESTED_SERVICES,
        scopes=GOOGLE_GMAIL_SEND_SCOPES,
        access_label=("read-only Gmail, Calendar, and Drive access plus permission to send Gmail"),
    ),
}


@dataclass(frozen=True)
class GoogleWorkspaceWorkerHandoff:
    """One in-memory central OAuth handoff worker context."""

    client: PlatformClient
    platform_auth: str
    handoff_id: str
    owner_token: str
    private_key_pem: str
    expected_capability_bundle: str
    expected_services: list[str]
    expected_scopes: list[str]


@dataclass(frozen=True)
class GoogleWorkspaceDisconnectIntent:
    """One platform-owned disconnect ceremony polled by this Computer."""

    client: PlatformClient
    platform_auth: str
    intent_id: str
    owner_token: str
    credential_generation: str
    expires_at: str
    poll_after_ms: int


@dataclass(frozen=True)
class GoogleWorkspaceDisconnectCompletionReceipt:
    """Durable proof that polling must resume completion without another delete."""

    phase: str
    outcome: str
    error_code: str | None


def google_workspace(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Connect, inspect, or disconnect this Computer's Google account."""
    # A prior worker may have exhausted its bounded completion window while
    # the platform was unavailable. Any later plugin use automatically
    # restarts retained idempotent receipts; this never replays OAuth polling.
    with contextlib.suppress(Exception):
        _resume_retained_disconnect_workers()
    payload = args if isinstance(args, dict) else {}
    raw_action = payload.get("action")
    if not isinstance(raw_action, str) or not raw_action.strip():
        return tool_error_json(
            tool="tinyhat_google_workspace",
            error_name="missing_required_parameter",
            message=(
                "Call tinyhat_google_workspace with action='connect', "
                "action='status', or action='disconnect'."
            ),
            missing=["action"],
            example_call={"action": "connect"},
        )

    action = raw_action.strip().lower()
    if action not in GOOGLE_WORKSPACE_ACTIONS:
        return tool_error_json(
            tool="tinyhat_google_workspace",
            error_name="invalid_parameter",
            message=(
                "Unsupported tinyhat_google_workspace action. Use one of: "
                + ", ".join(GOOGLE_WORKSPACE_ACTIONS)
                + "."
            ),
            expected={"action": list(GOOGLE_WORKSPACE_ACTIONS)},
            example_call={"action": "status"},
        )

    raw_profile = payload.get("profile")
    if action != "connect" and raw_profile is not None:
        return tool_error_json(
            tool="tinyhat_google_workspace",
            error_name="invalid_parameter",
            message="The profile parameter is accepted only with action='connect'.",
            expected={"profile": list(GOOGLE_WORKSPACE_PROFILES)},
            example_call={"action": "connect", "profile": GOOGLE_WORKSPACE_PROFILE_READONLY},
        )

    if action == "status":
        try:
            result = _status_payload()
        except Exception:
            result = {
                "schema": "tinyhat_google_workspace_status_v1",
                "action": "status",
                "status": "verification_unavailable",
                "connected": False,
                "message": "Google identity status could not be verified safely.",
            }
    elif action == "disconnect":
        try:
            # A model-provided boolean is not human confirmation. The platform
            # sends an authenticated two-stage Telegram ceremony and the
            # detached Computer worker acts only after its terminal confirm.
            result = _start_disconnect_intent()
        except Exception:
            result = {
                "schema": "tinyhat_google_workspace_action_v1",
                "action": "disconnect",
                "status": "failed",
                "connected": True,
                "button_sent": False,
                "message": (
                    "I could not start the Google Workspace disconnect prompt. "
                    "The existing connection is unchanged. Please try again."
                ),
            }
    else:
        try:
            profile = _requested_profile(raw_profile)
        except GoogleWorkspaceError:
            return tool_error_json(
                tool="tinyhat_google_workspace",
                error_name="invalid_parameter",
                message=(
                    "Unsupported Google Workspace permission profile. Use one of: "
                    + ", ".join(GOOGLE_WORKSPACE_PROFILES)
                    + "."
                ),
                expected={"profile": list(GOOGLE_WORKSPACE_PROFILES)},
                example_call={
                    "action": "connect",
                    "profile": GOOGLE_WORKSPACE_PROFILE_READONLY,
                },
            )
        if (
            profile.name == GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND
            and payload.get("confirmed") is not True
        ):
            return tool_error_json(
                tool="tinyhat_google_workspace",
                error_name="confirmation_required",
                message=(
                    "Ask the user to explicitly confirm upgrading this Google Workspace "
                    "connection so the agent may send Gmail. This permission upgrade is "
                    "separate from confirming any later email send. It adds gmail.send "
                    "only; Gmail draft management is not enabled."
                ),
                example_call={
                    "action": "connect",
                    "profile": GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND,
                    "confirmed": True,
                },
            )
        try:
            result = _start_connection(profile=profile)
        except Exception:
            result = {
                "schema": "tinyhat_google_workspace_action_v1",
                "action": "connect",
                "status": "failed",
                "message": ("I could not start Google sign-in on this Computer. Please try again."),
            }
    return json.dumps(result, sort_keys=True)


def _requested_profile(value: Any) -> GoogleWorkspaceProfile:
    if value is None:
        return GOOGLE_PROFILE_CONFIGS[GOOGLE_WORKSPACE_PROFILE_READONLY]
    if not isinstance(value, str):
        raise GoogleWorkspaceError("Google Workspace profile must be a string.")
    profile = GOOGLE_PROFILE_CONFIGS.get(value.strip().lower())
    if profile is None:
        raise GoogleWorkspaceError("Google Workspace profile is not allowlisted.")
    return profile


def _profile_for_capability_bundle(value: Any) -> GoogleWorkspaceProfile:
    for profile in GOOGLE_PROFILE_CONFIGS.values():
        if value == profile.capability_bundle:
            return profile
    raise GoogleWorkspaceError("Platform returned an unexpected capability bundle.")


def _start_connection(*, profile: GoogleWorkspaceProfile | None = None) -> dict[str, Any]:
    requested_profile = profile or GOOGLE_PROFILE_CONFIGS[GOOGLE_WORKSPACE_PROFILE_READONLY]
    private_key_pem, public_key_pem = _generate_key_pair()
    generation = secrets.token_urlsafe(32)
    # Serialize the complete start transition. A disconnect that begins after
    # this connect waits until its marker exists, then cancels it. A second
    # connect supersedes the first marker before either worker may install.
    with _lifecycle_lock():
        # A new connection attempt supersedes any unconfirmed disconnect
        # ceremony. Its worker keeps polling only long enough to observe the
        # superseded platform state; the missing local marker prevents deletion.
        ACTIVE_DISCONNECT_PATH.unlink(missing_ok=True)
        _wipe_invalid_credentials_and_pending_handoffs_locked()
        client, platform_auth = build_platform_client()
        handoff = client.post_json(
            computer_api_path(platform_auth, GOOGLE_WORKSPACE_API_SUFFIX),
            {
                "public_key_pem": public_key_pem,
                "key_algorithm": KEY_ALGORITHM,
                "capability_bundle": requested_profile.capability_bundle,
                "requested_services": list(requested_profile.services),
                "requested_scopes": list(requested_profile.scopes),
            },
        )
        handoff_id = _validated_handoff_id(handoff.get("handoff_id"))
        capability_bundle = _validated_capability_bundle(
            handoff.get("capability_bundle"),
            expected=requested_profile.capability_bundle,
        )
        services = _normalize_workspace_services(
            handoff.get("services"),
            expected=requested_profile.services,
        )
        scopes = _normalize_workspace_scopes(
            handoff.get("scopes"),
            expected=requested_profile.scopes,
        )
        poll_after_ms = _poll_after_ms(handoff.get("poll_after_ms"))
        authorization_url = _validated_authorization_url(handoff.get("authorization_url"))
        try:
            _start_worker_process(
                handoff=handoff,
                private_key_pem=private_key_pem,
                generation=generation,
                handoff_metadata={
                    "capability_bundle": capability_bundle,
                    "services": services,
                    "scopes": scopes,
                },
            )
        except Exception:
            with contextlib.suppress(Exception):
                _claim_handoff(
                    client=client,
                    platform_auth=platform_auth,
                    handoff_id=handoff_id,
                    installed=False,
                    message="Google sign-in worker could not start.",
                )
            raise
        button_result = (
            _send_google_connect_button(authorization_url)
            if requested_profile.name == GOOGLE_WORKSPACE_PROFILE_READONLY
            else _send_google_connect_button(
                authorization_url,
                profile=requested_profile.name,
            )
        )
        if not button_result.get("ok"):
            with contextlib.suppress(Exception):
                _claim_handoff(
                    client=client,
                    platform_auth=platform_auth,
                    handoff_id=handoff_id,
                    installed=False,
                    message="Connect Google button could not be delivered.",
                )
            raise GoogleWorkspaceError("Could not deliver the Connect Google button.")
    private_key_pem = ""
    generation = ""
    return {
        "schema": "tinyhat_google_workspace_action_v1",
        "action": "connect",
        "profile": requested_profile.name,
        "capability_bundle": requested_profile.capability_bundle,
        "status": "waiting_for_user",
        "button_sent": True,
        "poll_after_ms": poll_after_ms,
        "message": (
            "I sent a native Connect Google button in Telegram. Use that button "
            f"to approve {requested_profile.access_label} plus basic identity. "
            "No plain authorization link is returned. Your existing connection "
            "stays usable unless the expanded credential is completed successfully."
        ),
        "handoff_started": bool(handoff_id),
    }


def _validated_handoff_id(value: Any) -> str:
    handoff_id = str(value or "").strip()
    if HANDOFF_ID_RE.fullmatch(handoff_id) is None:
        raise GoogleWorkspaceError("Platform returned an invalid handoff id.")
    return handoff_id


def _validated_authorization_url(value: Any) -> str:
    authorization_url = str(value or "").strip()
    parsed = parse.urlsplit(authorization_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise GoogleWorkspaceError(
            "Platform returned an invalid Google authorization URL."
        ) from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != GOOGLE_AUTHORIZATION_HOST
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path != GOOGLE_AUTHORIZATION_PATH
        or not parsed.query
        or parsed.fragment
        or len(authorization_url) > AUTHORIZATION_URL_MAX_LENGTH
    ):
        raise GoogleWorkspaceError("Platform returned an invalid Google authorization URL.")
    return authorization_url


def _send_google_connect_button(
    authorization_url: str,
    *,
    profile: str = GOOGLE_WORKSPACE_PROFILE_READONLY,
) -> dict[str, bool]:
    """Send the platform URL only inside a native Telegram button."""
    requested_profile = _requested_profile(profile)
    try:
        # Lazy import avoids the tools -> google_workspace registration cycle.
        from .tools import _telegram_credentials, _telegram_send_message  # noqa: PLC0415

        token, chat_id = _telegram_credentials()
        sent = _telegram_send_message(
            token=token,
            chat_id=chat_id,
            text=(f"Connect Google Workspace with {requested_profile.access_label}."),
            reply_markup={
                "inline_keyboard": [[{"text": "Connect Google", "url": authorization_url}]]
            },
        )
        ok = bool(sent.get("ok"))
        return {"sent": ok, "ok": ok}
    except Exception:
        return {"sent": False, "ok": False}


def _validated_capability_bundle(value: Any, *, expected: str | None = None) -> str:
    profile = _profile_for_capability_bundle(value)
    if expected is not None and profile.capability_bundle != expected:
        raise GoogleWorkspaceError("Platform returned an unexpected capability bundle.")
    return profile.capability_bundle


def _normalize_workspace_services(
    value: Any,
    *,
    expected: tuple[str, ...] = GOOGLE_REQUESTED_SERVICES,
) -> list[str]:
    if value != list(expected):
        raise GoogleWorkspaceError("Platform returned unexpected Google services.")
    return list(expected)


def _poll_after_ms(value: Any) -> int:
    try:
        parsed = int(value or 2000)
    except (TypeError, ValueError):
        parsed = 2000
    return min(10_000, max(1000, parsed))


DISCONNECT_INTENT_STATUSES = frozenset(
    {
        "created",
        "offered",
        "awaiting_confirmation",
        "confirmed",
        "cancelled",
        "disconnected",
        "failed",
        "expired",
        "superseded",
    }
)
DISCONNECT_INTENT_WAITING_STATUSES = frozenset({"created", "offered", "awaiting_confirmation"})
DISCONNECT_INTENT_TERMINAL_STATUSES = frozenset(
    {"cancelled", "disconnected", "failed", "expired", "superseded"}
)


def _trusted_telegram_user_id() -> int:
    """Return the Computer's configured private-chat user id, never its bot token."""
    from .tools import _telegram_credentials  # noqa: PLC0415

    _bot_token, chat_id = _telegram_credentials()
    try:
        telegram_user_id = int(str(chat_id).strip())
    except (TypeError, ValueError) as exc:
        raise GoogleWorkspaceError("Telegram user identity is invalid.") from exc
    if telegram_user_id <= 0:
        raise GoogleWorkspaceError("Telegram user identity is invalid.")
    return telegram_user_id


def _start_disconnect_intent() -> dict[str, Any]:
    """Start the platform-owned two-stage Telegram disconnect ceremony."""
    credentials, verification = _verified_credentials()
    if credentials is None:
        if verification in {"not_present", "removed"}:
            return {
                "schema": "tinyhat_google_workspace_action_v1",
                "action": "disconnect",
                "status": "not_connected",
                "connected": False,
                "button_sent": False,
                "message": "Google Workspace is not connected on this Computer.",
            }
        raise GoogleWorkspaceError(
            "Google Workspace ownership could not be verified for disconnect."
        )

    telegram_user_id = _trusted_telegram_user_id()
    client, platform_auth = build_platform_client()
    created = client.post_json(
        computer_api_path(
            platform_auth,
            GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX,
        ),
        {"telegram_user_id": telegram_user_id},
    )
    intent = _normalize_disconnect_intent_create(
        created,
        client=client,
        platform_auth=platform_auth,
    )
    state_path: Path | None = None
    worker_started = False
    try:
        with _lifecycle_lock():
            current = _read_credentials()
            if current is None:
                raise GoogleWorkspaceError(
                    "Google Workspace was disconnected before the prompt started."
                )
            expected_generation = _credential_generation(
                credentials,
                owner_token=intent.owner_token,
            )
            current_generation = _credential_generation(
                current,
                owner_token=intent.owner_token,
            )
            if not hmac.compare_digest(expected_generation, current_generation):
                raise GoogleWorkspaceError(
                    "Google Workspace credentials changed before the prompt started."
                )
            current_binding = _fetch_assignment_binding(
                client=client,
                platform_auth=platform_auth,
            )
            if not hmac.compare_digest(
                str(current["tinyhat_assignment_binding"]),
                current_binding,
            ):
                raise GoogleWorkspaceError("Computer assignment changed before the prompt started.")

            intent = GoogleWorkspaceDisconnectIntent(
                client=intent.client,
                platform_auth=intent.platform_auth,
                intent_id=intent.intent_id,
                owner_token=intent.owner_token,
                credential_generation=current_generation,
                expires_at=intent.expires_at,
                poll_after_ms=intent.poll_after_ms,
            )

            # A newer disconnect ceremony supersedes the older local owner
            # marker. The older worker can still poll long enough to learn its
            # platform terminal state, but it can no longer delete anything.
            state_path = _write_disconnect_worker_state(
                intent=intent,
                credential_generation=current_generation,
            )
            _write_active_disconnect_marker(
                intent_id=intent.intent_id,
                owner_token=intent.owner_token,
                credential_generation=current_generation,
            )
            _start_disconnect_worker_process(
                intent_id=intent.intent_id,
                state_path=state_path,
            )
            worker_started = True

        activated = client.post_json(
            computer_api_path(
                platform_auth,
                f"{GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX}/{intent.intent_id}/activate",
            ),
            {"owner_token": intent.owner_token},
        )
        activated_status = _normalize_disconnect_intent_response(
            activated,
            expected_intent_id=intent.intent_id,
        )
        if activated_status not in {"offered", "awaiting_confirmation"}:
            raise GoogleWorkspaceError("Platform did not activate the Google disconnect prompt.")
        if activated.get("button_sent") is not True:
            raise GoogleWorkspaceError("Platform did not deliver the Google disconnect button.")
    except Exception:
        with contextlib.suppress(Exception), _lifecycle_lock():
            _remove_active_disconnect_marker_if_matches(
                intent_id=intent.intent_id,
                owner_token=intent.owner_token,
                credential_generation=intent.credential_generation,
            )
        with contextlib.suppress(Exception):
            _complete_disconnect_intent(
                intent=intent,
                outcome="failed",
                error_code=("activation_failed" if worker_started else "worker_start_failed"),
            )
        if not worker_started and state_path is not None:
            _cleanup_disconnect_worker_state(state_path)
        raise

    # Do not expose the platform intent id, owner token, or Mini App URL to the
    # model. The tool-sent Telegram message is the entire user-facing surface.
    return {
        "schema": "tinyhat_google_workspace_action_v1",
        "action": "disconnect",
        "status": "waiting_for_user",
        "connected": True,
        "button_sent": True,
        "message": (
            "I sent a native Telegram button labeled Revoke this Computer's "
            "access. Its first tap changes the same message to final Confirm "
            "revoke and Cancel buttons. The existing connection stays unchanged "
            "unless Confirm revoke is tapped. This local disconnect does "
            "not revoke Google's shared OAuth grant."
        ),
    }


def _normalize_disconnect_intent_create(
    value: Any,
    *,
    client: PlatformClient,
    platform_auth: str,
) -> GoogleWorkspaceDisconnectIntent:
    if not isinstance(value, dict):
        raise GoogleWorkspaceError("Platform returned an invalid disconnect intent.")
    if value.get("schema") != GOOGLE_WORKSPACE_DISCONNECT_INTENT_SCHEMA:
        raise GoogleWorkspaceError("Platform returned an invalid disconnect schema.")
    if value.get("status") != "created":
        raise GoogleWorkspaceError("Platform did not create the disconnect intent.")
    intent_id = _validated_handoff_id(value.get("intent_id"))
    owner_token = _validated_disconnect_owner_token(value.get("owner_token"))
    expires_at = _validated_disconnect_expires_at(value.get("expires_at"))
    return GoogleWorkspaceDisconnectIntent(
        client=client,
        platform_auth=platform_auth,
        intent_id=intent_id,
        owner_token=owner_token,
        credential_generation="",
        expires_at=expires_at,
        poll_after_ms=_poll_after_ms(value.get("poll_after_ms")),
    )


def _normalize_disconnect_intent_response(
    value: Any,
    *,
    expected_intent_id: str,
) -> str:
    if not isinstance(value, dict):
        raise GoogleWorkspaceError("Platform returned invalid disconnect state.")
    schema = value.get("schema")
    if schema is not None and schema != GOOGLE_WORKSPACE_DISCONNECT_INTENT_SCHEMA:
        raise GoogleWorkspaceError("Platform returned an invalid disconnect schema.")
    returned_id = value.get("intent_id")
    if returned_id is not None and _validated_handoff_id(returned_id) != expected_intent_id:
        raise GoogleWorkspaceError("Platform returned another disconnect intent.")
    status = str(value.get("status") or "").strip().lower()
    if status not in DISCONNECT_INTENT_STATUSES:
        raise GoogleWorkspaceError("Platform returned unknown disconnect state.")
    return status


def _validated_disconnect_owner_token(value: Any) -> str:
    owner_token = str(value or "").strip()
    if DISCONNECT_OWNER_TOKEN_RE.fullmatch(owner_token) is None:
        raise GoogleWorkspaceError("Platform returned an invalid disconnect owner token.")
    return owner_token


def _validated_disconnect_expires_at(
    value: Any,
    *,
    require_future: bool = True,
) -> str:
    expires_at = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoogleWorkspaceError("Platform returned an invalid disconnect expiry.") from exc
    now = datetime.now(timezone.utc)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GoogleWorkspaceError("Platform returned an invalid disconnect expiry.")
    if require_future and parsed <= now:
        raise GoogleWorkspaceError("Platform returned an invalid disconnect expiry.")
    if parsed.timestamp() > now.timestamp() + DEFAULT_EXPIRES_IN_SECONDS + 60:
        raise GoogleWorkspaceError("Platform returned an excessive disconnect expiry.")
    return expires_at


def _credential_generation(
    credentials: dict[str, Any],
    *,
    owner_token: str,
) -> str:
    """Bind one disconnect ceremony to one exact refresh credential generation."""
    clean_owner_token = _validated_disconnect_owner_token(owner_token)
    material = {
        key: credentials.get(key)
        for key in (
            "schema",
            "capability_bundle",
            "client_id",
            "refresh_token",
            "google_subject",
            "email",
            "connected_at",
            "tinyhat_assignment_binding",
        )
    }
    encoded = json.dumps(
        material,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hmac.new(
        clean_owner_token.encode("ascii"),
        encoded,
        hashlib.sha256,
    ).hexdigest()


def _write_disconnect_worker_state(
    *,
    intent: GoogleWorkspaceDisconnectIntent,
    credential_generation: str,
) -> Path:
    if DISCONNECT_GENERATION_RE.fullmatch(credential_generation) is None:
        raise GoogleWorkspaceError("Google disconnect generation is invalid.")
    _ensure_private_directory(STATE_DIR)
    _ensure_private_directory(DISCONNECTS_DIR)
    directory = DISCONNECTS_DIR / intent.intent_id
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    directory.chmod(0o700)
    state_path = directory / "intent.json"
    try:
        _write_private_file(
            state_path,
            json.dumps(
                {
                    "schema": GOOGLE_WORKSPACE_DISCONNECT_WORKER_STATE_SCHEMA,
                    "intent_id": intent.intent_id,
                    "owner_token": intent.owner_token,
                    "credential_generation": credential_generation,
                    "expires_at": intent.expires_at,
                    "poll_after_ms": intent.poll_after_ms,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    except Exception:
        _cleanup_disconnect_worker_state(state_path)
        raise
    return state_path


def _validated_disconnect_worker_state(
    *, intent_id: str, state_path: Path
) -> dict[str, Any]:
    clean_intent_id = _validated_handoff_id(intent_id)
    expected_path = DISCONNECTS_DIR / clean_intent_id / "intent.json"
    if state_path != expected_path or state_path.parent.parent != DISCONNECTS_DIR:
        raise GoogleWorkspaceError("Google disconnect worker path is invalid.")
    value = _read_owner_only_json(
        state_path,
        label="Google disconnect worker state",
    )
    allowed_fields = {
        "schema",
        "intent_id",
        "owner_token",
        "credential_generation",
        "expires_at",
        "poll_after_ms",
    }
    if set(value) != allowed_fields:
        raise GoogleWorkspaceError("Google disconnect worker state is invalid.")
    if value.get("schema") != GOOGLE_WORKSPACE_DISCONNECT_WORKER_STATE_SCHEMA:
        raise GoogleWorkspaceError("Google disconnect worker schema is invalid.")
    if _validated_handoff_id(value.get("intent_id")) != clean_intent_id:
        raise GoogleWorkspaceError("Google disconnect worker intent changed.")
    generation = str(value.get("credential_generation") or "").strip()
    if DISCONNECT_GENERATION_RE.fullmatch(generation) is None:
        raise GoogleWorkspaceError("Google disconnect worker generation is invalid.")
    return {
        "intent_id": clean_intent_id,
        "owner_token": _validated_disconnect_owner_token(value.get("owner_token")),
        "credential_generation": generation,
        "expires_at": _validated_disconnect_expires_at(
            value.get("expires_at"),
            require_future=False,
        ),
        "poll_after_ms": _poll_after_ms(value.get("poll_after_ms")),
    }


def _load_disconnect_worker_intent(
    *,
    intent_id: str,
    state_path: Path,
    client: PlatformClient,
    platform_auth: str,
) -> GoogleWorkspaceDisconnectIntent:
    value = _validated_disconnect_worker_state(
        intent_id=intent_id,
        state_path=state_path,
    )
    return GoogleWorkspaceDisconnectIntent(
        client=client,
        platform_auth=platform_auth,
        intent_id=value["intent_id"],
        owner_token=value["owner_token"],
        credential_generation=value["credential_generation"],
        expires_at=value["expires_at"],
        poll_after_ms=value["poll_after_ms"],
    )


def _disconnect_worker_ready_path(*, intent_id: str, state_path: Path) -> Path:
    clean_intent_id = _validated_handoff_id(intent_id)
    expected_state_path = DISCONNECTS_DIR / clean_intent_id / "intent.json"
    if state_path != expected_state_path or state_path.parent.parent != DISCONNECTS_DIR:
        raise GoogleWorkspaceError("Google disconnect worker path is invalid.")
    return state_path.parent / "ready.json"


def _disconnect_completion_receipt_path(*, intent_id: str, state_path: Path) -> Path:
    clean_intent_id = _validated_handoff_id(intent_id)
    expected_state_path = DISCONNECTS_DIR / clean_intent_id / "intent.json"
    if state_path != expected_state_path or state_path.parent.parent != DISCONNECTS_DIR:
        raise GoogleWorkspaceError("Google disconnect worker path is invalid.")
    return state_path.parent / "completion-receipt.json"


def _normalize_disconnect_receipt_terminal(
    value: dict[str, Any],
) -> GoogleWorkspaceDisconnectCompletionReceipt:
    phase = str(value.get("phase") or "").strip()
    outcome = str(value.get("outcome") or "").strip()
    raw_error_code = value.get("error_code")
    error_code = None if raw_error_code is None else str(raw_error_code).strip()
    valid = (
        phase in {"delete_pending", "completion_pending"}
        and outcome == "disconnected"
        and error_code is None
    ) or (phase == "completion_pending" and outcome == "failed" and error_code == "expired")
    if not valid:
        raise GoogleWorkspaceError("Google disconnect completion receipt is invalid.")
    return GoogleWorkspaceDisconnectCompletionReceipt(
        phase=phase,
        outcome=outcome,
        error_code=error_code,
    )


def _load_disconnect_completion_receipt(
    *,
    intent: GoogleWorkspaceDisconnectIntent,
    state_path: Path,
) -> GoogleWorkspaceDisconnectCompletionReceipt | None:
    receipt_path = _disconnect_completion_receipt_path(
        intent_id=intent.intent_id,
        state_path=state_path,
    )
    if not os.path.lexists(receipt_path):
        return None
    value = _read_owner_only_json(
        receipt_path,
        label="Google disconnect completion receipt",
    )
    if set(value) != {
        "schema",
        "intent_id",
        "owner_generation",
        "credential_generation",
        "phase",
        "outcome",
        "error_code",
        "recorded_at",
    }:
        raise GoogleWorkspaceError("Google disconnect completion receipt is invalid.")
    if value.get("schema") != GOOGLE_WORKSPACE_DISCONNECT_COMPLETION_RECEIPT_SCHEMA:
        raise GoogleWorkspaceError("Google disconnect completion receipt is invalid.")
    if _validated_handoff_id(value.get("intent_id")) != intent.intent_id:
        raise GoogleWorkspaceError("Google disconnect completion receipt changed intent.")
    if not hmac.compare_digest(
        str(value.get("owner_generation") or ""),
        _handoff_owner_token(intent.owner_token),
    ) or not hmac.compare_digest(
        str(value.get("credential_generation") or ""),
        intent.credential_generation,
    ):
        raise GoogleWorkspaceError("Google disconnect completion receipt changed owner.")
    receipt = _normalize_disconnect_receipt_terminal(value)
    try:
        recorded_at = datetime.fromisoformat(str(value.get("recorded_at")).replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoogleWorkspaceError("Google disconnect completion receipt is invalid.") from exc
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise GoogleWorkspaceError("Google disconnect completion receipt is invalid.")
    return receipt


def _write_disconnect_completion_receipt(
    *,
    intent: GoogleWorkspaceDisconnectIntent,
    state_path: Path,
    phase: str,
    outcome: str,
    error_code: str | None,
) -> None:
    valid_receipt = phase in {"delete_pending", "completion_pending"} and (
        (outcome == "disconnected" and error_code is None)
        or (outcome == "failed" and error_code == "expired")
    )
    if outcome == "failed" and phase != "completion_pending":
        valid_receipt = False
    if not valid_receipt:
        raise GoogleWorkspaceError("Google disconnect completion receipt is invalid.")
    receipt_path = _disconnect_completion_receipt_path(
        intent_id=intent.intent_id,
        state_path=state_path,
    )
    if os.path.lexists(receipt_path):
        existing = _load_disconnect_completion_receipt(
            intent=intent,
            state_path=state_path,
        )
        if existing == GoogleWorkspaceDisconnectCompletionReceipt(
            phase=phase,
            outcome=outcome,
            error_code=error_code,
        ):
            return
        if (
            existing.phase == "delete_pending"
            and phase == "completion_pending"
            and existing.outcome == outcome
            and existing.error_code == error_code
        ):
            pass
        else:
            raise GoogleWorkspaceError("Google disconnect completion receipt already exists.")
    _atomic_write_json(
        path=receipt_path,
        value={
            "schema": GOOGLE_WORKSPACE_DISCONNECT_COMPLETION_RECEIPT_SCHEMA,
            "intent_id": intent.intent_id,
            "owner_generation": _handoff_owner_token(intent.owner_token),
            "credential_generation": intent.credential_generation,
            "phase": phase,
            "outcome": outcome,
            "error_code": error_code,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        },
        temporary_prefix=".completion-receipt-",
    )


def _resume_delete_pending_receipt(
    *,
    intent: GoogleWorkspaceDisconnectIntent,
    state_path: Path,
) -> str:
    """Idempotently reclaim a pre-delete receipt before recovery."""
    with _lifecycle_lock():
        claim_status = _claim_disconnect_deletion(intent)
        if claim_status != "confirmed":
            _remove_active_disconnect_marker_if_matches(
                intent_id=intent.intent_id,
                owner_token=intent.owner_token,
                credential_generation=intent.credential_generation,
            )
            return claim_status
        if _read_credentials() is not None:
            return "delete_required"
        _write_disconnect_completion_receipt(
            intent=intent,
            state_path=state_path,
            phase="completion_pending",
            outcome="disconnected",
            error_code=None,
        )
        _remove_active_disconnect_marker_if_matches(
            intent_id=intent.intent_id,
            owner_token=intent.owner_token,
            credential_generation=intent.credential_generation,
        )
        return "completion_pending"


def _write_disconnect_worker_ready(*, intent_id: str, state_path: Path) -> None:
    ready_path = _disconnect_worker_ready_path(
        intent_id=intent_id,
        state_path=state_path,
    )
    expected = {
        "schema": GOOGLE_WORKSPACE_DISCONNECT_WORKER_READY_SCHEMA,
        "intent_id": _validated_handoff_id(intent_id),
    }
    if os.path.lexists(ready_path):
        existing = _read_owner_only_json(
            ready_path,
            label="Google disconnect worker readiness",
        )
        if existing == expected:
            return
        raise GoogleWorkspaceError("Google disconnect worker readiness is invalid.")
    _write_private_file(
        ready_path,
        json.dumps(
            expected,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )


def _wait_for_disconnect_worker_ready(
    *,
    intent_id: str,
    state_path: Path,
    timeout_seconds: float = DISCONNECT_WORKER_READY_TIMEOUT_SECONDS,
) -> None:
    ready_path = _disconnect_worker_ready_path(
        intent_id=intent_id,
        state_path=state_path,
    )
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while time.monotonic() < deadline:
        try:
            ready = _read_owner_only_json(
                ready_path,
                label="Google disconnect worker readiness",
            )
        except GoogleWorkspaceError as exc:
            if os.path.lexists(ready_path):
                raise
            if not os.path.lexists(state_path):
                raise GoogleWorkspaceError(
                    "Google disconnect worker stopped before readiness."
                ) from exc
            time.sleep(DISCONNECT_WORKER_READY_POLL_SECONDS)
            continue
        if ready != {
            "schema": GOOGLE_WORKSPACE_DISCONNECT_WORKER_READY_SCHEMA,
            "intent_id": _validated_handoff_id(intent_id),
        }:
            raise GoogleWorkspaceError("Google disconnect worker readiness is invalid.")
        return
    raise GoogleWorkspaceError("Google disconnect worker did not become ready.")


def _write_active_disconnect_marker(
    *,
    intent_id: str,
    owner_token: str,
    credential_generation: str,
) -> None:
    _atomic_write_json(
        path=ACTIVE_DISCONNECT_PATH,
        value={
            "intent_id": _validated_handoff_id(intent_id),
            "owner_generation": _handoff_owner_token(owner_token),
            "credential_generation": credential_generation,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        temporary_prefix=".active-disconnect-",
    )


def _active_disconnect_matches_locked(
    *,
    intent_id: str,
    owner_token: str,
    credential_generation: str,
) -> bool:
    try:
        marker = _read_owner_only_json(
            ACTIVE_DISCONNECT_PATH,
            label="Active Google disconnect marker",
        )
    except GoogleWorkspaceError:
        return False
    return bool(
        marker.get("intent_id") == intent_id
        and hmac.compare_digest(
            str(marker.get("owner_generation") or ""),
            _handoff_owner_token(owner_token),
        )
        and hmac.compare_digest(
            str(marker.get("credential_generation") or ""),
            credential_generation,
        )
    )


def _active_disconnect_matches(intent: GoogleWorkspaceDisconnectIntent) -> bool:
    with _lifecycle_lock():
        return _active_disconnect_matches_locked(
            intent_id=intent.intent_id,
            owner_token=intent.owner_token,
            credential_generation=intent.credential_generation,
        )


def _remove_active_disconnect_marker_if_matches(
    *,
    intent_id: str,
    owner_token: str,
    credential_generation: str,
) -> bool:
    if not _active_disconnect_matches_locked(
        intent_id=intent_id,
        owner_token=owner_token,
        credential_generation=credential_generation,
    ):
        return False
    ACTIVE_DISCONNECT_PATH.unlink(missing_ok=True)
    return True


def _start_disconnect_worker_process(*, intent_id: str, state_path: Path) -> None:
    package_dir = Path(__file__).resolve().parent
    env = os.environ.copy()
    pythonpath = str(package_dir.parent)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONPATH"] = pythonpath
    command = _disconnect_worker_command(
        intent_id=intent_id,
        state_path=state_path,
        package_dir=package_dir,
    )
    try:
        started_with_systemd = _start_disconnect_worker_with_systemd(
            intent_id=intent_id,
            command=command,
            package_dir=package_dir,
            env=env,
        )
        if not started_with_systemd:
            subprocess.Popen(
                command,
                cwd=str(package_dir.parent),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        _wait_for_disconnect_worker_ready(
            intent_id=intent_id,
            state_path=state_path,
        )
    except Exception as exc:
        raise GoogleWorkspaceError("Could not start the Google disconnect worker.") from exc


def _start_disconnect_worker_with_systemd(
    *,
    intent_id: str,
    command: list[str],
    package_dir: Path,
    env: dict[str, str],
) -> bool:
    if env.get("TINYHAT_LOCAL_DEV_TOKEN"):
        return False
    systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        return False
    systemd_command = [
        systemd_run,
        "--user",
        "--collect",
        "--quiet",
        f"--unit=tinyhat-google-disconnect-{intent_id[:48]}",
    ]
    for key in WORKER_SYSTEMD_ENV_KEYS:
        if key in env:
            systemd_command.append(f"--setenv={key}={env[key]}")
    systemd_command.extend(command)
    try:
        completed = subprocess.run(
            systemd_command,
            cwd=str(package_dir.parent),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _disconnect_worker_command(
    *,
    intent_id: str,
    state_path: Path,
    package_dir: Path,
) -> list[str]:
    return [
        sys.executable,
        str(package_dir / "google_workspace_disconnect_worker.py"),
        "--intent-id",
        intent_id,
        "--state-path",
        str(state_path),
    ]


def _retry_disconnect_completion(
    *,
    intent: GoogleWorkspaceDisconnectIntent,
    outcome: str,
    error_code: str | None = None,
) -> bool:
    """Retry one idempotent platform receipt through its Redis grace window."""
    deadline = time.monotonic() + DISCONNECT_COMPLETION_RETRY_SECONDS
    retry_delay = max(1.0, intent.poll_after_ms / 1000)
    while True:
        try:
            _complete_disconnect_intent(
                intent=intent,
                outcome=outcome,
                error_code=error_code,
            )
            return True
        except Exception:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(retry_delay, remaining))
            retry_delay = min(
                retry_delay * 2,
                DISCONNECT_COMPLETION_MAX_RETRY_DELAY_SECONDS,
            )


def _poll_disconnect_intent(
    intent: GoogleWorkspaceDisconnectIntent,
    *,
    record_completion_receipt: Callable[[str, str, str | None], None] | None = None,
) -> str:
    deadline = datetime.fromisoformat(intent.expires_at.replace("Z", "+00:00")).timestamp()
    while time.time() < deadline:
        if not _active_disconnect_matches(intent):
            with contextlib.suppress(Exception):
                _complete_disconnect_intent(
                    intent=intent,
                    outcome="failed",
                    error_code="superseded",
                )
            return "superseded"
        try:
            state = intent.client.post_json(
                computer_api_path(
                    intent.platform_auth,
                    f"{GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX}/{intent.intent_id}/poll",
                ),
                {"owner_token": intent.owner_token},
            )
            status = _normalize_disconnect_intent_response(
                state,
                expected_intent_id=intent.intent_id,
            )
            if state.get("expires_at") is not None:
                returned_deadline = datetime.fromisoformat(
                    _validated_disconnect_expires_at(
                        state.get("expires_at"),
                        require_future=False,
                    ).replace("Z", "+00:00")
                ).timestamp()
                # The create-time expiry is authoritative. A poll response may
                # shorten the intent but can never roll a live revoke prompt
                # forward indefinitely.
                deadline = min(deadline, returned_deadline)
        except Exception:
            time.sleep(intent.poll_after_ms / 1000)
            continue

        if status in DISCONNECT_INTENT_WAITING_STATUSES:
            time.sleep(_poll_after_ms(state.get("poll_after_ms")) / 1000)
            continue
        if status == "confirmed":
            outcome = _delete_confirmed_disconnect(
                intent,
                record_completion_receipt=record_completion_receipt,
            )
            if outcome != "disconnected":
                if (
                    outcome not in DISCONNECT_INTENT_TERMINAL_STATUSES
                    and outcome != "deletion_claim_pending"
                ):
                    with contextlib.suppress(Exception):
                        _complete_disconnect_intent(
                            intent=intent,
                            outcome="failed",
                            error_code=outcome,
                        )
                return outcome
            if _retry_disconnect_completion(
                intent=intent,
                outcome="disconnected",
            ):
                return "disconnected"
            return "completion_pending"
        if status in DISCONNECT_INTENT_TERMINAL_STATUSES:
            with _lifecycle_lock():
                _remove_active_disconnect_marker_if_matches(
                    intent_id=intent.intent_id,
                    owner_token=intent.owner_token,
                    credential_generation=intent.credential_generation,
                )
            return status

    # The Computer owns the create-time deadline. Best-effort terminalization
    # lets the platform remove an untapped Telegram button instead of waiting
    # for Redis retention cleanup. Failure here never changes local credentials.
    if record_completion_receipt is not None:
        record_completion_receipt("completion_pending", "failed", "expired")
    completion_acknowledged = _retry_disconnect_completion(
        intent=intent,
        outcome="failed",
        error_code="expired",
    )
    with _lifecycle_lock():
        _remove_active_disconnect_marker_if_matches(
            intent_id=intent.intent_id,
            owner_token=intent.owner_token,
            credential_generation=intent.credential_generation,
        )
    return "expired" if completion_acknowledged else "expiry_completion_pending"


def _claim_disconnect_deletion(intent: GoogleWorkspaceDisconnectIntent) -> str:
    """Claim the confirmed platform intent immediately before local unlink."""
    response = intent.client.post_json(
        computer_api_path(
            intent.platform_auth,
            f"{GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX}/{intent.intent_id}/claim",
        ),
        {"owner_token": intent.owner_token},
    )
    status = _normalize_disconnect_intent_response(
        response,
        expected_intent_id=intent.intent_id,
    )
    if status == "confirmed" and response.get("deletion_claimed") is True:
        return "confirmed"
    if status in DISCONNECT_INTENT_TERMINAL_STATUSES:
        return status
    return "deletion_claim_rejected"


def _current_disconnect_credential_status(
    intent: GoogleWorkspaceDisconnectIntent,
) -> tuple[dict[str, Any] | None, str]:
    current = _read_credentials()
    if current is None:
        return None, "disconnected"
    current_generation = _credential_generation(
        current,
        owner_token=intent.owner_token,
    )
    if not hmac.compare_digest(
        current_generation,
        intent.credential_generation,
    ):
        return current, "credential_changed"
    current_binding = _fetch_assignment_binding(
        client=intent.client,
        platform_auth=intent.platform_auth,
    )
    if not hmac.compare_digest(
        str(current["tinyhat_assignment_binding"]),
        current_binding,
    ):
        return current, "assignment_changed"
    return current, "disconnected"


def _delete_confirmed_disconnect(
    intent: GoogleWorkspaceDisconnectIntent,
    *,
    record_completion_receipt: Callable[[str, str, str | None], None] | None = None,
) -> str:
    """Delete only the exact credential generation targeted by this intent."""
    local_terminal_confirmed = False
    claim_attempted = False
    credential_presence_verified = False
    credential_present = False
    try:
        with _lifecycle_lock():
            result = "disconnected"
            current: dict[str, Any] | None = None
            if not _active_disconnect_matches_locked(
                intent_id=intent.intent_id,
                owner_token=intent.owner_token,
                credential_generation=intent.credential_generation,
            ):
                result = "superseded"
            else:
                current, result = _current_disconnect_credential_status(intent)
                credential_presence_verified = True
                credential_present = current is not None
            if result == "disconnected":
                if record_completion_receipt is not None:
                    record_completion_receipt(
                        "delete_pending",
                        "disconnected",
                        None,
                    )
                claim_attempted = True
                claim_status = _claim_disconnect_deletion(intent)
                if claim_status != "confirmed":
                    result = (
                        "deletion_claim_pending"
                        if not credential_present and claim_status == "deletion_claim_rejected"
                        else claim_status
                    )
                else:
                    if current is not None:
                        _cancel_pending_handoffs_for_disconnect_locked()
                        _delete_credentials_locked()
                    local_terminal_confirmed = True
                    if record_completion_receipt is not None:
                        # The durable pre-delete receipt is already sufficient
                        # to recover an unlink. Promotion must not turn that
                        # terminal action into local_delete_failed.
                        with contextlib.suppress(Exception):
                            record_completion_receipt(
                                "completion_pending",
                                "disconnected",
                                None,
                            )
            _remove_active_disconnect_marker_if_matches(
                intent_id=intent.intent_id,
                owner_token=intent.owner_token,
                credential_generation=intent.credential_generation,
            )
    except Exception:
        if local_terminal_confirmed:
            return "disconnected"
        if claim_attempted and (not credential_presence_verified or not credential_present):
            return "deletion_claim_pending"
        return "local_delete_failed"
    return result


def _complete_disconnect_intent(
    *,
    intent: GoogleWorkspaceDisconnectIntent,
    outcome: str,
    error_code: str | None = None,
) -> dict[str, Any]:
    if outcome not in {"disconnected", "failed"}:
        raise GoogleWorkspaceError("Google disconnect outcome is invalid.")
    payload: dict[str, Any] = {
        "owner_token": intent.owner_token,
        "outcome": outcome,
    }
    if outcome == "failed" and error_code:
        payload["error_code"] = error_code[:63]
    response = intent.client.post_json(
        computer_api_path(
            intent.platform_auth,
            f"{GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX}/{intent.intent_id}/complete",
        ),
        payload,
    )
    status = _normalize_disconnect_intent_response(
        response,
        expected_intent_id=intent.intent_id,
    )
    if outcome == "disconnected" and status != "disconnected":
        raise GoogleWorkspaceError("Platform did not complete the disconnect.")
    return response


def _cleanup_disconnect_worker_state(state_path: Path) -> None:
    try:
        intent_id = _validated_handoff_id(state_path.parent.name)
    except GoogleWorkspaceError:
        return
    expected_path = DISCONNECTS_DIR / intent_id / "intent.json"
    if state_path != expected_path or state_path.parent.parent != DISCONNECTS_DIR:
        return
    try:
        parent_stat = os.lstat(DISCONNECTS_DIR)
        intent_stat = os.lstat(state_path.parent)
    except OSError:
        return
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.getuid()
        or not stat.S_ISDIR(intent_stat.st_mode)
        or intent_stat.st_uid != os.getuid()
    ):
        return
    with contextlib.suppress(OSError):
        shutil.rmtree(state_path.parent)


def _sweep_expired_receiptless_disconnect_state(  # noqa: PLR0911
    *, intent_id: str, state_path: Path
) -> bool:
    """Delete one expired owner-only scratch entry that cannot resume safely."""
    receipt_path = state_path.parent / "completion-receipt.json"
    if os.path.lexists(receipt_path):
        return False
    try:
        value = _validated_disconnect_worker_state(
            intent_id=intent_id,
            state_path=state_path,
        )
        deadline = datetime.fromisoformat(
            str(value["expires_at"]).replace("Z", "+00:00")
        ).timestamp()
    except (GoogleWorkspaceError, OSError, ValueError):
        return False
    if time.time() <= deadline + DISCONNECT_ORPHAN_SWEEP_GRACE_SECONDS:
        return False

    with _lifecycle_lock():
        if os.path.lexists(receipt_path):
            return False
        try:
            parent_stat = os.lstat(DISCONNECTS_DIR)
            directory_stat = os.lstat(state_path.parent)
            value = _validated_disconnect_worker_state(
                intent_id=intent_id,
                state_path=state_path,
            )
            deadline = datetime.fromisoformat(
                str(value["expires_at"]).replace("Z", "+00:00")
            ).timestamp()
        except (GoogleWorkspaceError, OSError, ValueError):
            return False
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_uid != os.getuid()
            or stat.S_IMODE(parent_stat.st_mode) & 0o077
            or not stat.S_ISDIR(directory_stat.st_mode)
            or directory_stat.st_uid != os.getuid()
            or stat.S_IMODE(directory_stat.st_mode) & 0o077
            or time.time() <= deadline + DISCONNECT_ORPHAN_SWEEP_GRACE_SECONDS
        ):
            return False
        _remove_active_disconnect_marker_if_matches(
            intent_id=str(value["intent_id"]),
            owner_token=str(value["owner_token"]),
            credential_generation=str(value["credential_generation"]),
        )
        _cleanup_disconnect_worker_state(state_path)
    return not os.path.lexists(state_path.parent)


def _resume_retained_disconnect_workers() -> int:  # noqa: PLR0912
    """Boundedly sweep orphan scratch and resume durable completion receipts."""
    try:
        parent_stat = os.lstat(DISCONNECTS_DIR)
        children = sorted(DISCONNECTS_DIR.iterdir(), key=lambda path: path.name)
    except (FileNotFoundError, OSError):
        return 0
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.getuid()
        or stat.S_IMODE(parent_stat.st_mode) & 0o077
    ):
        return 0
    candidates = children[:DISCONNECT_ORPHAN_SWEEP_SCAN_LIMIT]
    swept = 0
    for directory in candidates:
        if swept >= DISCONNECT_ORPHAN_SWEEP_DELETE_LIMIT:
            break
        try:
            intent_id = _validated_handoff_id(directory.name)
            directory_stat = os.lstat(directory)
        except (GoogleWorkspaceError, OSError):
            continue
        if (
            not stat.S_ISDIR(directory_stat.st_mode)
            or directory_stat.st_uid != os.getuid()
            or stat.S_IMODE(directory_stat.st_mode) & 0o077
        ):
            continue
        state_path = directory / "intent.json"
        if not os.path.lexists(state_path):
            continue
        if _sweep_expired_receiptless_disconnect_state(
            intent_id=intent_id,
            state_path=state_path,
        ):
            swept += 1

    started = 0
    for directory in children:
        if started >= DISCONNECT_AUTO_RESUME_LIMIT:
            break
        try:
            intent_id = _validated_handoff_id(directory.name)
            directory_stat = os.lstat(directory)
        except (GoogleWorkspaceError, OSError):
            continue
        if (
            not stat.S_ISDIR(directory_stat.st_mode)
            or directory_stat.st_uid != os.getuid()
            or stat.S_IMODE(directory_stat.st_mode) & 0o077
        ):
            continue
        state_path = directory / "intent.json"
        receipt_path = directory / "completion-receipt.json"
        if not os.path.lexists(state_path) or not os.path.lexists(receipt_path):
            continue
        try:
            _start_disconnect_worker_process(
                intent_id=intent_id,
                state_path=state_path,
            )
        except Exception:
            continue
        started += 1
    return started


def _start_worker_process(
    *,
    handoff: dict[str, Any],
    private_key_pem: str,
    generation: str,
    handoff_metadata: dict[str, Any],
) -> None:
    """Activate and spawn a worker while the caller holds the lifecycle lock."""
    handoff_id = _validated_handoff_id(handoff.get("handoff_id"))
    owner_token = _handoff_owner_token(generation)
    key_path = _write_worker_state(
        handoff_id=handoff_id,
        private_key_pem=private_key_pem,
        generation=generation,
        handoff_metadata=handoff_metadata,
    )
    _write_active_handoff_marker(handoff_id=handoff_id, owner_token=owner_token)
    package_dir = Path(__file__).resolve().parent
    env = os.environ.copy()
    pythonpath = str(package_dir.parent)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONPATH"] = pythonpath
    try:
        if _start_worker_with_systemd(
            handoff_id=handoff_id,
            key_path=key_path,
            package_dir=package_dir,
            env=env,
        ):
            return
        _start_worker_with_popen(
            handoff_id=handoff_id,
            key_path=key_path,
            package_dir=package_dir,
            env=env,
        )
    except Exception as exc:
        _remove_active_handoff_marker_if_matches(
            handoff_id=handoff_id,
            owner_token=owner_token,
        )
        _cleanup_worker_state(key_path)
        raise GoogleWorkspaceError("Could not start the Google sign-in worker.") from exc


def _write_worker_state(
    *,
    handoff_id: str,
    private_key_pem: str,
    generation: str,
    handoff_metadata: dict[str, Any],
) -> Path:
    _ensure_private_directory(STATE_DIR)
    _ensure_private_directory(HANDOFFS_DIR)
    directory = HANDOFFS_DIR / handoff_id
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    directory.chmod(0o700)
    key_path = directory / "private.pem"
    generation_path = directory / "generation"
    metadata_path = directory / "handoff-metadata.json"
    try:
        _write_private_file(key_path, private_key_pem)
        _write_private_file(generation_path, generation)
        _write_private_file(
            metadata_path,
            json.dumps(handoff_metadata, separators=(",", ":"), sort_keys=True),
        )
    except Exception:
        _cleanup_worker_state(key_path)
        raise
    return key_path


def _write_private_file(path: Path, value: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        with contextlib.suppress(OSError):
            path.unlink()
        raise


@contextlib.contextmanager
def _lifecycle_lock() -> Iterator[None]:
    """Serialize connect, install, and disconnect across plugin processes."""
    _ensure_private_directory(STATE_DIR)
    fd = os.open(
        LIFECYCLE_LOCK_PATH,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(fd, 0o600)
        lock_stat = os.fstat(fd)
        if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != os.getuid():
            raise GoogleWorkspaceError("Google Workspace lifecycle lock is unsafe.")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _handoff_owner_token(generation: str) -> str:
    return hashlib.sha256(generation.encode("ascii")).hexdigest()


def _write_active_handoff_marker(*, handoff_id: str, owner_token: str) -> None:
    _atomic_write_json(
        path=ACTIVE_HANDOFF_PATH,
        value={
            "handoff_id": _validated_handoff_id(handoff_id),
            "generation": owner_token,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        temporary_prefix=".active-handoff-",
    )


def _active_handoff_matches_locked(*, handoff_id: str, owner_token: str) -> bool:
    try:
        marker = json.loads(ACTIVE_HANDOFF_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(marker, dict)
        and marker.get("handoff_id") == handoff_id
        and marker.get("generation") == owner_token
    )


def _active_handoff_matches(*, handoff_id: str, owner_token: str) -> bool:
    with _lifecycle_lock():
        return _active_handoff_matches_locked(
            handoff_id=handoff_id,
            owner_token=owner_token,
        )


def _remove_active_handoff_marker_if_matches(*, handoff_id: str, owner_token: str) -> bool:
    if not _active_handoff_matches_locked(
        handoff_id=handoff_id,
        owner_token=owner_token,
    ):
        return False
    ACTIVE_HANDOFF_PATH.unlink(missing_ok=True)
    return True


def _cancel_all_pending_handoffs_locked() -> None:
    ACTIVE_HANDOFF_PATH.unlink(missing_ok=True)
    try:
        children = list(HANDOFFS_DIR.iterdir())
    except FileNotFoundError:
        return
    parent_stat = os.lstat(HANDOFFS_DIR)
    if not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != os.getuid():
        raise GoogleWorkspaceError("Google sign-in scratch directory is unsafe.")
    for child in children:
        candidate_key = child / "private.pem"
        _cleanup_worker_state(candidate_key)
    HANDOFFS_DIR.rmdir()


def _cancel_pending_handoffs_for_disconnect_locked() -> None:
    """Prevent credential resurrection even when stale scratch cleanup fails."""
    # Failure to remove the active marker is unsafe and must abort deletion.
    ACTIVE_HANDOFF_PATH.unlink(missing_ok=True)
    # Once the marker is gone, no handoff worker may install. Leftover private
    # scratch is owner-only and can be cleaned by a later lifecycle operation;
    # it must not block a user-confirmed credential deletion.
    with contextlib.suppress(Exception):
        _cancel_all_pending_handoffs_locked()


def _atomic_write_json(*, path: Path, value: dict[str, Any], temporary_prefix: str) -> None:
    _ensure_private_directory(path.parent)
    fd, temporary_name = tempfile.mkstemp(prefix=temporary_prefix, dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            temporary_path.unlink()


def _start_worker_with_systemd(
    *,
    handoff_id: str,
    key_path: Path,
    package_dir: Path,
    env: dict[str, str],
) -> bool:
    # systemd-run receives --setenv values in argv. Local development tokens
    # therefore use the detached Popen path, which inherits the protected
    # process environment without exposing the token in command arguments.
    if env.get("TINYHAT_LOCAL_DEV_TOKEN"):
        return False
    systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        return False
    command = [
        systemd_run,
        "--user",
        "--collect",
        "--quiet",
        f"--unit=tinyhat-google-workspace-{handoff_id[:48]}",
    ]
    for key in WORKER_SYSTEMD_ENV_KEYS:
        if key in env:
            command.append(f"--setenv={key}={env[key]}")
    command.extend(
        _worker_command(
            handoff_id=handoff_id,
            key_path=key_path,
            package_dir=package_dir,
        )
    )
    try:
        completed = subprocess.run(
            command,
            cwd=str(package_dir.parent),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _start_worker_with_popen(
    *,
    handoff_id: str,
    key_path: Path,
    package_dir: Path,
    env: dict[str, str],
) -> None:
    subprocess.Popen(
        _worker_command(
            handoff_id=handoff_id,
            key_path=key_path,
            package_dir=package_dir,
        ),
        cwd=str(package_dir.parent),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def _worker_command(*, handoff_id: str, key_path: Path, package_dir: Path) -> list[str]:
    return [
        sys.executable,
        str(package_dir / "google_workspace_worker.py"),
        "--handoff-id",
        handoff_id,
        "--key-path",
        str(key_path),
    ]


def _poll_and_install(handoff: GoogleWorkspaceWorkerHandoff) -> None:
    deadline = time.time() + DEFAULT_EXPIRES_IN_SECONDS
    installed = False
    notification_attempted = False
    try:
        while time.time() < deadline:
            if not _active_handoff_matches(
                handoff_id=handoff.handoff_id,
                owner_token=handoff.owner_token,
            ):
                notification_attempted = True
                _claim_superseded(
                    client=handoff.client,
                    platform_auth=handoff.platform_auth,
                    handoff_id=handoff.handoff_id,
                )
                return
            state = handoff.client.get_json(
                computer_api_path(
                    handoff.platform_auth,
                    f"{GOOGLE_WORKSPACE_API_SUFFIX}/{handoff.handoff_id}",
                )
            )
            deadline = _deadline_from_state(state, deadline)
            status = str(state.get("status") or "").strip().lower()
            terminal_state = str(state.get("terminal_state") or "").strip().lower()
            if not terminal_state and status in {
                "ready",
                "cancelled",
                "failed",
                "expired",
                "superseded",
            }:
                terminal_state = status
            if terminal_state == "ready":
                outcome = _install_ready_credentials(handoff=handoff, state=state)
                if outcome == "superseded":
                    notification_attempted = True
                    _claim_superseded(
                        client=handoff.client,
                        platform_auth=handoff.platform_auth,
                        handoff_id=handoff.handoff_id,
                    )
                    return
                if outcome == "assignment_changed":
                    notification_attempted = True
                    _send_google_workspace_notice("failed")
                    _claim_handoff(
                        client=handoff.client,
                        platform_auth=handoff.platform_auth,
                        handoff_id=handoff.handoff_id,
                        installed=False,
                        message="Computer assignment changed before Google sign-in completed.",
                    )
                    return
                installed = True
                notification_attempted = True
                ready_notice = (
                    "ready_gmail_send"
                    if handoff.expected_capability_bundle == GOOGLE_GMAIL_SEND_CAPABILITY_BUNDLE
                    else "ready"
                )
                _send_google_workspace_notice(ready_notice)
                _claim_handoff(
                    client=handoff.client,
                    platform_auth=handoff.platform_auth,
                    handoff_id=handoff.handoff_id,
                    installed=True,
                    message=None,
                )
                return
            if terminal_state in TERMINAL_HANDOFF_MESSAGES:
                notification_attempted = True
                _finish_terminal_handoff(
                    handoff=handoff,
                    terminal_state=terminal_state,
                )
                return
            if status == "claimed":
                _clear_active_handoff(handoff)
                return
            time.sleep(_poll_after_ms(state.get("poll_after_ms")) / 1000)
        notification_attempted = True
        _finish_terminal_handoff(handoff=handoff, terminal_state="expired")
    except Exception:
        with contextlib.suppress(Exception), _lifecycle_lock():
            _remove_active_handoff_marker_if_matches(
                handoff_id=handoff.handoff_id,
                owner_token=handoff.owner_token,
            )
        with contextlib.suppress(Exception):
            _claim_handoff(
                client=handoff.client,
                platform_auth=handoff.platform_auth,
                handoff_id=handoff.handoff_id,
                installed=installed,
                message=None if installed else TERMINAL_HANDOFF_MESSAGES["failed"],
            )
        if not notification_attempted:
            _send_google_workspace_notice("ready" if installed else "failed")
        raise


TERMINAL_HANDOFF_MESSAGES = {
    "cancelled": "Google sign-in was cancelled. Start connect again when you are ready.",
    "failed": "Google sign-in failed. Start a new connection and try again.",
    "expired": "Google sign-in expired. Start connect again for a fresh link.",
    "superseded": "This Google sign-in was replaced by a newer connection attempt.",
}

TELEGRAM_NOTICE_MESSAGES = {
    "ready": (
        "Google Workspace is connected on this Computer with read-only access "
        "to Gmail, Calendar, and Drive."
    ),
    "ready_gmail_send": (
        "Google Workspace permissions were updated on this Computer. Read-only "
        "Gmail, Calendar, and Drive access remains available, and Gmail sending "
        "is now enabled. I will still ask before sending an email."
    ),
    "cancelled": (
        "Google Workspace connection was cancelled. Ask me to connect Google "
        "again when you are ready."
    ),
    "failed": (
        "Google Workspace connection failed. Ask me to connect Google again "
        "and I will create a fresh link."
    ),
    "expired": (
        "The Google Workspace connection link expired. Ask me to connect Google "
        "again for a fresh link."
    ),
    "superseded": ("This Google Workspace connection was replaced by a newer connection attempt."),
}


def _send_google_workspace_notice(terminal_state: str) -> dict[str, bool]:
    """Send one fixed terminal notice without exposing handoff details."""
    text = TELEGRAM_NOTICE_MESSAGES.get(terminal_state)
    if text is None:
        return {"sent": False, "ok": False}
    try:
        # Import lazily because tools imports this module for tool registration.
        from .tools import _telegram_credentials, _telegram_send_message  # noqa: PLC0415

        token, chat_id = _telegram_credentials()
        sent = _telegram_send_message(
            token=token,
            chat_id=chat_id,
            text=text,
        )
        ok = bool(sent.get("ok"))
        return {"sent": ok, "ok": ok}
    except Exception:
        return {"sent": False, "ok": False}


def _clear_active_handoff(handoff: GoogleWorkspaceWorkerHandoff) -> None:
    with _lifecycle_lock():
        _remove_active_handoff_marker_if_matches(
            handoff_id=handoff.handoff_id,
            owner_token=handoff.owner_token,
        )


def _finish_terminal_handoff(*, handoff: GoogleWorkspaceWorkerHandoff, terminal_state: str) -> None:
    _clear_active_handoff(handoff)
    _send_google_workspace_notice(terminal_state)
    _claim_handoff(
        client=handoff.client,
        platform_auth=handoff.platform_auth,
        handoff_id=handoff.handoff_id,
        installed=False,
        message=TERMINAL_HANDOFF_MESSAGES[terminal_state],
    )


def _install_ready_credentials(
    *, handoff: GoogleWorkspaceWorkerHandoff, state: dict[str, Any]
) -> str:
    credentials = _decrypt_ready_credentials(handoff.private_key_pem, state)
    if credentials["capability_bundle"] != handoff.expected_capability_bundle:
        raise GoogleWorkspaceError("Google capability bundle changed during handoff.")
    if credentials["services"] != handoff.expected_services:
        raise GoogleWorkspaceError("Google services changed during handoff.")
    if credentials["scopes"] != handoff.expected_scopes:
        raise GoogleWorkspaceError("Google scopes changed during handoff.")
    with _lifecycle_lock():
        if not _active_handoff_matches_locked(
            handoff_id=handoff.handoff_id,
            owner_token=handoff.owner_token,
        ):
            return "superseded"
        if not _assignment_binding_matches_platform(
            credentials=credentials,
            client=handoff.client,
            platform_auth=handoff.platform_auth,
        ):
            _cancel_all_pending_handoffs_locked()
            _delete_credentials_locked()
            return "assignment_changed"
        _remove_active_handoff_marker_if_matches(
            handoff_id=handoff.handoff_id,
            owner_token=handoff.owner_token,
        )
        _atomic_save_credentials(credentials)
    return "installed"


def _claim_superseded(*, client: PlatformClient, platform_auth: str, handoff_id: str) -> None:
    _send_google_workspace_notice("superseded")
    _claim_handoff(
        client=client,
        platform_auth=platform_auth,
        handoff_id=handoff_id,
        installed=False,
        message=TERMINAL_HANDOFF_MESSAGES["superseded"],
    )


def _deadline_from_state(state: dict[str, Any], fallback: float) -> float:
    expires_at = str(state.get("expires_at") or "").strip()
    if not expires_at:
        return fallback
    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _decrypt_ready_credentials(private_key_pem: str, state: dict[str, Any]) -> dict[str, Any]:
    ciphertext_payload = state.get("ciphertext_payload")
    if not isinstance(ciphertext_payload, dict):
        raise GoogleWorkspaceError("Platform did not return encrypted Google credentials.")
    plaintext = _decrypt_ciphertext(private_key_pem, ciphertext_payload)
    try:
        decoded = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise GoogleWorkspaceError("Encrypted Google credentials were invalid.") from exc
    finally:
        plaintext = ""
    return _normalize_credentials(decoded)


def _normalize_credentials(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GoogleWorkspaceError("Google credential envelope must be an object.")
    if {"client_secret", "authorization_code", "code_verifier"}.intersection(value):
        raise GoogleWorkspaceError("Google credential envelope contained a server-only field.")
    if value.get("schema") != GOOGLE_WORKSPACE_CREDENTIAL_SCHEMA:
        raise GoogleWorkspaceError("Google credential envelope schema was invalid.")

    required_strings = (
        "client_id",
        "access_token",
        "refresh_token",
        "token_type",
        "expires_at",
        "google_subject",
        "email",
        "tinyhat_assignment_binding",
    )
    profile = _profile_for_capability_bundle(value.get("capability_bundle"))
    normalized: dict[str, Any] = {
        "schema": GOOGLE_WORKSPACE_CREDENTIAL_SCHEMA,
        "capability_bundle": profile.capability_bundle,
        "services": _normalize_workspace_services(
            value.get("services"),
            expected=profile.services,
        ),
        "token_uri": _validated_token_uri(value.get("token_uri")),
    }
    for key in required_strings:
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            raise GoogleWorkspaceError(f"Google credential envelope was missing {key}.")
        normalized[key] = item.strip()
    normalized["client_id"] = _validated_public_client_id(normalized["client_id"])
    if normalized["token_type"].lower() != "bearer":
        raise GoogleWorkspaceError("Google credential envelope token type was invalid.")
    normalized["token_type"] = "Bearer"

    scopes = value.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        raise GoogleWorkspaceError("Google credential envelope was missing scopes.")
    normalized["scopes"] = _normalize_workspace_scopes(
        scopes,
        expected=profile.scopes,
    )

    email_verified = value.get("email_verified")
    if email_verified is not True:
        raise GoogleWorkspaceError("Google credential envelope email is not verified.")
    normalized["email_verified"] = True
    normalized["connected_at"] = datetime.now(timezone.utc).isoformat()
    return normalized


def _normalize_workspace_scopes(
    scopes: Any,
    *,
    expected: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    if expected is not None:
        expected_scopes = list(expected)
        if scopes != expected_scopes:
            raise GoogleWorkspaceError("Platform returned unexpected Google Workspace scopes.")
        return expected_scopes
    for profile in GOOGLE_PROFILE_CONFIGS.values():
        if scopes == list(profile.scopes):
            return list(profile.scopes)
    raise GoogleWorkspaceError("Platform returned unexpected Google Workspace scopes.")


def _validated_token_uri(value: Any) -> str:
    token_uri = str(value or "").strip()
    if token_uri != GOOGLE_TOKEN_URI:
        raise GoogleWorkspaceError("Google token endpoint was invalid.")
    return token_uri


def _validated_public_client_id(value: Any) -> str:
    client_id = str(value or "").strip()
    if (
        not client_id.endswith(".apps.googleusercontent.com")
        or len(client_id) > PUBLIC_CLIENT_ID_MAX_LENGTH
    ):
        raise GoogleWorkspaceError("Google credential envelope client id was invalid.")
    return client_id


def _atomic_save_credentials(credentials: dict[str, Any]) -> None:
    _refuse_unsafe_credentials_entry()
    _atomic_write_json(
        path=CREDENTIALS_PATH,
        value=credentials,
        temporary_prefix=".credentials-",
    )


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise GoogleWorkspaceError("Google Workspace state directory is unsafe.")
    path.chmod(0o700)


def _credentials_entry_exists() -> bool:
    try:
        os.lstat(CREDENTIALS_PATH)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _refuse_unsafe_owner_file(path: Path, *, label: str) -> os.stat_result:
    try:
        file_stat = os.lstat(path)
    except FileNotFoundError as exc:
        raise GoogleWorkspaceError(f"{label} is not configured.") from exc
    except OSError as exc:
        raise GoogleWorkspaceError(f"{label} cannot be inspected safely.") from exc
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_uid != os.getuid()
        or file_stat.st_nlink != 1
        or stat.S_IMODE(file_stat.st_mode) & 0o077
    ):
        raise GoogleWorkspaceError(f"{label} is not an owner-only regular file.")
    return file_stat


def _refuse_unsafe_owned_readable_file(path: Path, *, label: str) -> os.stat_result:
    """Allow safe unlink of an owned regular file even when its mode drifted."""
    try:
        file_stat = os.lstat(path)
    except OSError as exc:
        raise GoogleWorkspaceError(f"{label} cannot be inspected safely.") from exc
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_uid != os.getuid()
        or file_stat.st_nlink != 1
        or not file_stat.st_mode & stat.S_IRUSR
    ):
        raise GoogleWorkspaceError(f"{label} is not a safely removable owned file.")
    return file_stat


def _read_owner_only_json(path: Path, *, label: str) -> dict[str, Any]:
    before = _refuse_unsafe_owner_file(path, label=label)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            opened = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.getuid()
                or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or stat.S_IMODE(opened.st_mode) & 0o077
            ):
                raise GoogleWorkspaceError(f"{label} changed during secure open.")
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise GoogleWorkspaceError(f"{label} is invalid.") from exc
    if not isinstance(value, dict):
        raise GoogleWorkspaceError(f"{label} must be a JSON object.")
    return value


def _refuse_unsafe_credentials_entry() -> None:
    if not _credentials_entry_exists():
        return
    _refuse_unsafe_owner_file(CREDENTIALS_PATH, label="Saved Google credentials")


def _read_credentials() -> dict[str, Any] | None:
    if not _credentials_entry_exists():
        return None
    value = _read_owner_only_json(
        CREDENTIALS_PATH,
        label="Saved Google credentials",
    )
    normalized = _normalize_saved_credentials(value)
    return normalized


def _normalize_saved_credentials(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != GOOGLE_WORKSPACE_CREDENTIAL_SCHEMA:
        raise GoogleWorkspaceError("Saved Google credentials are invalid.")
    if "client_secret" in value:
        raise GoogleWorkspaceError("Saved Google credentials contain a server-only field.")
    required = (
        "capability_bundle",
        "token_uri",
        "client_id",
        "access_token",
        "refresh_token",
        "token_type",
        "expires_at",
        "google_subject",
        "email",
        "connected_at",
        "tinyhat_assignment_binding",
    )
    for key in required:
        if not isinstance(value.get(key), str) or not str(value.get(key)).strip():
            raise GoogleWorkspaceError("Saved Google credentials are incomplete.")
    if value.get("token_uri") != GOOGLE_TOKEN_URI:
        raise GoogleWorkspaceError("Saved Google credentials use an invalid token endpoint.")
    try:
        profile = _profile_for_capability_bundle(value.get("capability_bundle"))
        value["capability_bundle"] = profile.capability_bundle
        value["services"] = _normalize_workspace_services(
            value.get("services"),
            expected=profile.services,
        )
        normalized_scopes = _normalize_workspace_scopes(
            value.get("scopes"),
            expected=profile.scopes,
        )
    except GoogleWorkspaceError as exc:
        raise GoogleWorkspaceError("Saved Google credential metadata is invalid.") from exc
    if value.get("email_verified") is not True:
        raise GoogleWorkspaceError("Saved Google credential metadata is invalid.")
    value["scopes"] = normalized_scopes
    return value


def _fetch_assignment_binding(*, client: PlatformClient, platform_auth: str) -> str:
    response = client.get_json(
        computer_api_path(
            platform_auth,
            f"{GOOGLE_WORKSPACE_API_SUFFIX}/assignment-binding",
        )
    )
    binding = response.get("tinyhat_assignment_binding")
    if not isinstance(binding, str) or not binding.strip():
        raise GoogleWorkspaceError("Platform did not return an assignment binding.")
    return binding.strip()


def _assignment_binding_matches_platform(
    *,
    credentials: dict[str, Any],
    client: PlatformClient,
    platform_auth: str,
) -> bool:
    saved_binding = str(credentials.get("tinyhat_assignment_binding") or "")
    current_binding = _fetch_assignment_binding(
        client=client,
        platform_auth=platform_auth,
    )
    return hmac.compare_digest(saved_binding, current_binding)


def _delete_credentials_locked() -> None:
    # unlink removes a symlink itself without following it. Reads and writes
    # still refuse such entries through lstat and O_NOFOLLOW.
    CREDENTIALS_PATH.unlink(missing_ok=True)


def _wipe_invalid_credentials_and_pending_handoffs_locked() -> str:
    """Remove malformed owner-readable credentials and every pending handoff."""
    if not _credentials_entry_exists():
        return "not_present"
    try:
        credentials = _read_credentials()
    except GoogleWorkspaceError:
        # Only remove owner-readable regular files with no hard links. This may
        # include a mode-drifted file, but never follows a symlink or unlinks a
        # shared inode.
        _refuse_unsafe_owned_readable_file(
            CREDENTIALS_PATH,
            label="Saved Google credentials",
        )
        # Delete the credential first so a scratch-cleanup failure cannot leave
        # stale tokens available on the Computer.
        _delete_credentials_locked()
        ACTIVE_DISCONNECT_PATH.unlink(missing_ok=True)
        _cancel_all_pending_handoffs_locked()
        return "invalid"
    return "valid" if credentials is not None else "not_present"


def _wipe_invalid_credentials_and_pending_handoffs() -> str:
    with _lifecycle_lock():
        result = _wipe_invalid_credentials_and_pending_handoffs_locked()
    return "retry" if result == "valid" else result


def remove_credentials_if_assignment_changed(*, timeout_seconds: int | None = None) -> str:
    """Remove stale local credentials after an authoritative assignment change.

    This is intentionally cheap when no credential entry exists. A platform
    outage leaves the permission-protected file in place but returns
    ``unavailable`` so status and future consumers can fail closed.
    """
    local_status, credentials = _local_credentials_for_binding_check()
    if local_status == "invalid":
        return _wipe_invalid_credentials_and_pending_handoffs()
    if credentials is None:
        return local_status
    saved_binding = str(credentials["tinyhat_assignment_binding"])
    try:
        client_kwargs = (
            {} if timeout_seconds is None else {"timeout_seconds": timeout_seconds}
        )
        client, platform_auth = build_platform_client(**client_kwargs)
        current_binding = _fetch_assignment_binding(
            client=client,
            platform_auth=platform_auth,
        )
    except Exception:
        return "unavailable"
    if hmac.compare_digest(saved_binding, current_binding):
        return "match"
    return _remove_credentials_for_stale_binding(saved_binding)


def _context_assignment_cache_key(
    credentials: dict[str, Any],
) -> tuple[int, int, int, int, str] | None:
    try:
        entry = os.lstat(CREDENTIALS_PATH)
    except OSError:
        return None
    if (
        not stat.S_ISREG(entry.st_mode)
        or entry.st_uid != os.getuid()
        or entry.st_nlink != 1
        or stat.S_IMODE(entry.st_mode) != OWNER_ONLY_FILE_MODE
    ):
        return None
    return (
        entry.st_dev,
        entry.st_ino,
        entry.st_mtime_ns,
        entry.st_size,
        str(credentials.get("tinyhat_assignment_binding") or ""),
    )


def _clear_context_assignment_check_cache() -> None:
    with _context_assignment_check_cache_lock:
        _context_assignment_check_cache.clear()


def remove_credentials_if_assignment_changed_for_context() -> str:  # noqa: PLR0911
    """Best-effort eager cleanup without adding one long GET to every LLM turn.

    Only a recent positive assignment match is cached. Every credential
    consumer still performs the strict uncached verification before using a
    token, so this cache can delay eager cleanup but cannot authorize access.
    """
    local_status, credentials = _local_credentials_for_binding_check()
    if local_status == "invalid":
        _clear_context_assignment_check_cache()
        return _wipe_invalid_credentials_and_pending_handoffs()
    if credentials is None:
        _clear_context_assignment_check_cache()
        return local_status
    cache_key = _context_assignment_cache_key(credentials)
    if cache_key is None:
        _clear_context_assignment_check_cache()
        return "unavailable"
    now = time.monotonic()
    with _context_assignment_check_cache_lock:
        cached = _context_assignment_check_cache.get("assignment")
        if cached is not None and cached[0] == cache_key and cached[1] > now:
            return "match"
    result = remove_credentials_if_assignment_changed(
        timeout_seconds=CONTEXT_ASSIGNMENT_CHECK_TIMEOUT_SECONDS,
    )
    if result != "match":
        _clear_context_assignment_check_cache()
        return result
    current_status, current_credentials = _local_credentials_for_binding_check()
    current_key = (
        _context_assignment_cache_key(current_credentials)
        if current_status == "present" and current_credentials is not None
        else None
    )
    current_binding = (
        str(current_credentials.get("tinyhat_assignment_binding") or "")
        if current_credentials is not None
        else ""
    )
    if current_key is None or not hmac.compare_digest(
        current_binding,
        str(credentials["tinyhat_assignment_binding"]),
    ):
        _clear_context_assignment_check_cache()
        return "retry"
    with _context_assignment_check_cache_lock:
        _context_assignment_check_cache["assignment"] = (
            current_key,
            now + CONTEXT_ASSIGNMENT_CHECK_TTL_SECONDS,
        )
    return "match"


def _local_credentials_for_binding_check() -> tuple[str, dict[str, Any] | None]:
    if not _credentials_entry_exists():
        return "not_present", None
    try:
        credentials = _read_credentials()
    except GoogleWorkspaceError:
        return "invalid", None
    if credentials is None:
        return "not_present", None
    return "present", credentials


def _remove_credentials_for_stale_binding(saved_binding: str) -> str:
    with _lifecycle_lock():
        try:
            current_credentials = _read_credentials()
        except GoogleWorkspaceError:
            result = _wipe_invalid_credentials_and_pending_handoffs_locked()
            return "retry" if result == "valid" else result
        if current_credentials is None:
            return "not_present"
        current_local_binding = str(current_credentials["tinyhat_assignment_binding"])
        if not hmac.compare_digest(saved_binding, current_local_binding):
            return "retry"
        ACTIVE_DISCONNECT_PATH.unlink(missing_ok=True)
        _cancel_all_pending_handoffs_locked()
        _delete_credentials_locked()
    return "removed"


def _verified_credentials() -> tuple[dict[str, Any] | None, str]:
    for _ in range(2):
        verification = remove_credentials_if_assignment_changed()
        if verification == "retry":
            continue
        if verification != "match":
            return None, verification
        try:
            return _read_credentials(), "match"
        except GoogleWorkspaceError:
            return None, "invalid"
    return None, "unavailable"


def load_verified_google_workspace_credentials() -> dict[str, Any]:
    """Load credentials only after current-assignment verification.

    Gmail, Calendar, or Drive read-only operations must use this helper rather
    than reading the local file directly. The connection tool itself does not
    expose service data.
    """
    credentials, verification = _verified_credentials()
    if verification != "match" or credentials is None:
        raise GoogleWorkspaceError(
            "Google credentials are unavailable for the Computer's current assignment."
        )
    return credentials


def refresh_verified_google_workspace_credentials() -> dict[str, Any]:
    """Refresh Google access through the attested platform, never Google directly."""
    credentials = load_verified_google_workspace_credentials()
    profile = _profile_for_capability_bundle(credentials["capability_bundle"])
    private_key_pem, public_key_pem = _generate_key_pair()
    try:
        client, platform_auth = build_platform_client()
        response = client.post_json(
            computer_api_path(
                platform_auth,
                f"{GOOGLE_WORKSPACE_API_SUFFIX}/refresh",
            ),
            {
                "public_key_pem": public_key_pem,
                "key_algorithm": KEY_ALGORITHM,
                "client_id": credentials["client_id"],
                "refresh_token": credentials["refresh_token"],
                "tinyhat_assignment_binding": credentials["tinyhat_assignment_binding"],
                "capability_bundle": profile.capability_bundle,
                "requested_services": list(profile.services),
                "requested_scopes": list(profile.scopes),
            },
        )
        ciphertext_payload = response.get("ciphertext_payload")
        if not isinstance(ciphertext_payload, dict):
            raise GoogleWorkspaceError("Platform did not return encrypted refreshed Google access.")
        plaintext = _decrypt_ciphertext(private_key_pem, ciphertext_payload)
        try:
            decoded = json.loads(plaintext)
        except json.JSONDecodeError as exc:
            raise GoogleWorkspaceError("Refreshed Google access was invalid.") from exc
        finally:
            plaintext = ""
        refreshed = _normalize_refresh_document(
            decoded,
            expected_assignment_binding=str(credentials["tinyhat_assignment_binding"]),
            expected_scopes=profile.scopes,
        )
        return _persist_refreshed_credentials(
            expected=credentials,
            refreshed=refreshed,
            client=client,
            platform_auth=platform_auth,
        )
    except GoogleWorkspaceError:
        raise
    except Exception as exc:
        raise GoogleWorkspaceError("Google access could not be refreshed safely.") from exc
    finally:
        private_key_pem = ""


def _normalize_refresh_document(
    value: Any,
    *,
    expected_assignment_binding: str,
    expected_scopes: tuple[str, ...] | list[str] = GOOGLE_READONLY_SCOPES,
) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != GOOGLE_WORKSPACE_REFRESH_SCHEMA:
        raise GoogleWorkspaceError("Refreshed Google access had an invalid schema.")
    allowed_fields = {
        "schema",
        "access_token",
        "token_type",
        "expires_at",
        "scopes",
        "tinyhat_assignment_binding",
        "refresh_token",
    }
    if set(value) - allowed_fields:
        raise GoogleWorkspaceError("Refreshed Google access contained an unknown field.")

    access_token = value.get("access_token")
    token_type = value.get("token_type")
    expires_at = value.get("expires_at")
    assignment_binding = value.get("tinyhat_assignment_binding")
    if (
        not isinstance(access_token, str)
        or not access_token
        or len(access_token) > GOOGLE_TOKEN_VALUE_MAX_LENGTH
    ):
        raise GoogleWorkspaceError("Refreshed Google access was missing an access token.")
    if not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise GoogleWorkspaceError("Refreshed Google access had an invalid token type.")
    if not isinstance(expires_at, str) or len(expires_at) > GOOGLE_TOKEN_EXPIRY_MAX_LENGTH:
        raise GoogleWorkspaceError("Refreshed Google access had an invalid expiry.")
    try:
        parsed_expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoogleWorkspaceError("Refreshed Google access had an invalid expiry.") from exc
    if (
        parsed_expiry.tzinfo is None
        or parsed_expiry.utcoffset() is None
        or parsed_expiry <= datetime.now(timezone.utc)
    ):
        raise GoogleWorkspaceError("Refreshed Google access had an invalid expiry.")
    if not isinstance(assignment_binding, str) or not hmac.compare_digest(
        assignment_binding, expected_assignment_binding
    ):
        raise GoogleWorkspaceError("Computer assignment changed during Google refresh.")
    scopes = _normalize_workspace_scopes(
        value.get("scopes"),
        expected=expected_scopes,
    )
    rotated_refresh_token = value.get("refresh_token")
    if rotated_refresh_token is not None and (
        not isinstance(rotated_refresh_token, str)
        or not rotated_refresh_token
        or len(rotated_refresh_token) > GOOGLE_TOKEN_VALUE_MAX_LENGTH
    ):
        raise GoogleWorkspaceError("Refreshed Google access had an invalid refresh token.")
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_at": expires_at,
        "scopes": scopes,
        "tinyhat_assignment_binding": assignment_binding,
        "refresh_token": rotated_refresh_token,
    }


def _persist_refreshed_credentials(
    *,
    expected: dict[str, Any],
    refreshed: dict[str, Any],
    client: PlatformClient,
    platform_auth: str,
) -> dict[str, Any]:
    """Atomically update token fields without reviving disconnected credentials."""
    with _lifecycle_lock():
        current = _read_credentials()
        if current is None:
            raise GoogleWorkspaceError("Google Workspace was disconnected during refresh.")
        for field in ("client_id", "refresh_token", "tinyhat_assignment_binding"):
            if not hmac.compare_digest(str(current[field]), str(expected[field])):
                raise GoogleWorkspaceError("Google credentials changed during refresh.")
        platform_binding = _fetch_assignment_binding(
            client=client,
            platform_auth=platform_auth,
        )
        if not hmac.compare_digest(
            platform_binding,
            str(refreshed["tinyhat_assignment_binding"]),
        ):
            _delete_credentials_locked()
            raise GoogleWorkspaceError("Computer assignment changed during Google refresh.")

        current["access_token"] = refreshed["access_token"]
        current["token_type"] = refreshed["token_type"]
        current["expires_at"] = refreshed["expires_at"]
        rotated = refreshed.get("refresh_token")
        if isinstance(rotated, str) and rotated:
            current["refresh_token"] = rotated
        _atomic_save_credentials(current)
        return dict(current)


def _status_payload() -> dict[str, Any]:
    credentials, verification = _verified_credentials()
    if verification == "invalid":
        return {
            "schema": "tinyhat_google_workspace_status_v1",
            "action": "status",
            "status": "invalid",
            "connected": False,
            "message": "Google Workspace credentials need to be connected again.",
        }
    if verification == "unavailable":
        return {
            "schema": "tinyhat_google_workspace_status_v1",
            "action": "status",
            "status": "verification_unavailable",
            "connected": False,
            "message": (
                "The Computer could not verify that these Google credentials "
                "still belong to its current assignment. Try status again."
            ),
        }
    if credentials is None:
        return {
            "schema": "tinyhat_google_workspace_status_v1",
            "action": "status",
            "status": "not_connected",
            "connected": False,
            "connect_required": True,
            "message": (
                "No Google Workspace connection or active sign-in link exists on this "
                "Computer. If the user asked to connect, call tinyhat_google_workspace "
                "with action='connect' now and wait for the newly sent button. Do not "
                "reuse or claim that an earlier Connect Google button is still usable."
            ),
            "recommended_tool_call": {
                "tool": "tinyhat_google_workspace",
                "arguments": {"action": "connect"},
            },
        }
    profile = _profile_for_capability_bundle(credentials["capability_bundle"])
    return {
        "schema": "tinyhat_google_workspace_status_v1",
        "action": "status",
        "status": "connected",
        "connected": True,
        "profile": profile.name,
        "capability_bundle": profile.capability_bundle,
        "services": list(profile.services),
        "email": credentials["email"],
        "email_verified": credentials["email_verified"],
        "scopes": credentials["scopes"],
        "expires_at": credentials["expires_at"],
        "connected_at": credentials["connected_at"],
        "refresh_token_present": bool(credentials.get("refresh_token")),
        "refresh_supported": True,
        "refresh_mode": "tinyhat_platform_broker_v1",
        "refresh_available": bool(credentials.get("refresh_token")),
    }


def _claim_handoff(
    *,
    client: PlatformClient,
    platform_auth: str,
    handoff_id: str,
    installed: bool,
    message: str | None,
) -> None:
    client.post_json(
        computer_api_path(
            platform_auth,
            f"{GOOGLE_WORKSPACE_API_SUFFIX}/{handoff_id}/claim",
        ),
        {"installed": installed, "message": message},
    )


def _cleanup_worker_state(key_path: Path) -> None:
    try:
        handoff_id = _validated_handoff_id(key_path.parent.name)
    except GoogleWorkspaceError:
        return
    expected_key_path = HANDOFFS_DIR / handoff_id / "private.pem"
    if key_path != expected_key_path or key_path.parent.parent != HANDOFFS_DIR:
        return
    try:
        parent_stat = os.lstat(HANDOFFS_DIR)
        handoff_stat = os.lstat(key_path.parent)
    except OSError:
        return
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.getuid()
        or not stat.S_ISDIR(handoff_stat.st_mode)
        or handoff_stat.st_uid != os.getuid()
    ):
        return
    with contextlib.suppress(OSError):
        shutil.rmtree(key_path.parent)
