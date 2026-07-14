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

from .google_workspace_scope_manifest import (
    CLIENT_POLICIES_BY_ID,
    COMPATIBILITY_SCOPE_DISCLOSURES_BY_URL,
    IDENTITY_BUNDLE_ID,
    IDENTITY_SCOPE_URLS,
    MANIFEST,
    PRESET_ORDER,
    PRESETS_BY_ID,
    SCOPES_BY_URL,
    BlockedScope,
    ScopeResolution,
    blocked_scope_details,
    legacy_scope_urls,
    normalize_scope_urls,
    resolve_scope_request,
)
from .platform import (
    PlatformClient,
    PlatformError,
    build_platform_client,
    computer_api_path,
)
from .secret_handoff import KEY_ALGORITHM, _decrypt_ciphertext, _generate_key_pair
from .tool_errors import tool_error_json

GOOGLE_WORKSPACE_ACTIONS = ("connect", "status", "set_permissions", "disconnect")
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
GOOGLE_WORKSPACE_CREDENTIAL_SCHEMA = "tinyhat_google_workspace_credentials_v1"
GOOGLE_WORKSPACE_ACCOUNTS_SCHEMA = "tinyhat_google_workspace_accounts_v1"
GOOGLE_WORKSPACE_CONNECTIONS_SCHEMA = "tinyhat_google_workspace_connections_v1"
GOOGLE_WORKSPACE_REFRESH_SCHEMA = "tinyhat_google_workspace_refresh_v1"
GOOGLE_WORKSPACE_INSTALL_RECEIPT_SCHEMA = "tinyhat_google_workspace_install_receipt_v1"
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
GOOGLE_WORKSPACE_PREFLIGHT_SUFFIX = f"{GOOGLE_WORKSPACE_API_SUFFIX}/preflight"
GOOGLE_WORKSPACE_CONNECTIONS_SUFFIX = f"{GOOGLE_WORKSPACE_API_SUFFIX}/connections"
GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX = f"{GOOGLE_WORKSPACE_API_SUFFIX}/disconnect-intents"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_WORKSPACE_PROFILE_RECOMMENDED = "workspace_recommended"
GOOGLE_WORKSPACE_PROFILE_CUSTOM = "workspace_custom"
GOOGLE_WORKSPACE_PROFILE_READONLY = "workspace_readonly"
GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND = "gmail_send"
GOOGLE_WORKSPACE_PROFILE_CALENDAR_WRITE = "calendar_write"
GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND_CALENDAR_WRITE = "gmail_send_calendar_write"
# New request paths use manifest preset ids directly. The older profile ids
# below remain accepted only so callers receive a safe, explicit migration
# result and historical credentials can be reconstructed unchanged.
GOOGLE_WORKSPACE_PROFILE_IDENTITY = "identity_only"
GOOGLE_WORKSPACE_PROFILE_WORKSPACE_READER = "workspace_reader"
GOOGLE_WORKSPACE_PROFILE_MAIL_WRITER = "mail_writer"
GOOGLE_WORKSPACE_PROFILE_INBOX_MANAGER = "inbox_manager"
GOOGLE_WORKSPACE_PROFILE_CALENDAR_COORDINATOR = "calendar_coordinator"
GOOGLE_WORKSPACE_PROFILE_FILE_COLLABORATOR = "file_collaborator"
GOOGLE_WORKSPACE_PRESETS = tuple(PRESET_ORDER)
GOOGLE_WORKSPACE_PROFILES = (
    GOOGLE_WORKSPACE_PROFILE_RECOMMENDED,
    GOOGLE_WORKSPACE_PROFILE_READONLY,
    GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND,
    GOOGLE_WORKSPACE_PROFILE_CALENDAR_WRITE,
    GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND_CALENDAR_WRITE,
)
GOOGLE_IDENTITY_CAPABILITY_BUNDLE = IDENTITY_BUNDLE_ID
GOOGLE_WORKSPACE_READER_CAPABILITY_BUNDLE = str(
    PRESETS_BY_ID[GOOGLE_WORKSPACE_PROFILE_WORKSPACE_READER]["capability_bundle"]
)
GOOGLE_MAIL_WRITER_CAPABILITY_BUNDLE = str(
    PRESETS_BY_ID[GOOGLE_WORKSPACE_PROFILE_MAIL_WRITER]["capability_bundle"]
)
GOOGLE_INBOX_MANAGER_CAPABILITY_BUNDLE = str(
    PRESETS_BY_ID[GOOGLE_WORKSPACE_PROFILE_INBOX_MANAGER]["capability_bundle"]
)
GOOGLE_CALENDAR_COORDINATOR_CAPABILITY_BUNDLE = str(
    PRESETS_BY_ID[GOOGLE_WORKSPACE_PROFILE_CALENDAR_COORDINATOR]["capability_bundle"]
)
GOOGLE_FILE_COLLABORATOR_CAPABILITY_BUNDLE = str(
    PRESETS_BY_ID[GOOGLE_WORKSPACE_PROFILE_FILE_COLLABORATOR]["capability_bundle"]
)
GOOGLE_RECOMMENDED_CAPABILITY_BUNDLE = "google_workspace_recommended_v1"
GOOGLE_CUSTOM_CAPABILITY_BUNDLE = "google_workspace_custom_v1"
GOOGLE_READONLY_CAPABILITY_BUNDLE = "google_workspace_readonly_v1"
GOOGLE_GMAIL_SEND_CAPABILITY_BUNDLE = "google_workspace_gmail_send_v1"
GOOGLE_CALENDAR_WRITE_CAPABILITY_BUNDLE = "google_workspace_calendar_write_v1"
GOOGLE_GMAIL_SEND_CALENDAR_WRITE_CAPABILITY_BUNDLE = "google_workspace_gmail_send_calendar_write_v1"
GOOGLE_IDENTITY_SCOPES = tuple(IDENTITY_SCOPE_URLS)
GOOGLE_REQUESTED_SERVICES = ("identity", "gmail", "calendar", "drive")
# The plugin cannot know which central OAuth client the attested platform will
# select, so this local fallback intentionally permits manifest-reviewed
# development requests to reach preflight. It never authorizes OAuth: platform
# preflight is authoritative and stamps the actual client policy before any
# local state, worker, authorization URL, or Google button can be created.
GOOGLE_WORKSPACE_PLUGIN_POLICY_FALLBACK = "tinyhat-development"
GOOGLE_RECOMMENDED_SCOPES = (
    *GOOGLE_IDENTITY_SCOPES,
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
)
GOOGLE_READONLY_SCOPES = (
    *GOOGLE_IDENTITY_SCOPES,
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
)
GOOGLE_GMAIL_SEND_SCOPES = (
    *GOOGLE_READONLY_SCOPES,
    "https://www.googleapis.com/auth/gmail.send",
)
GOOGLE_CALENDAR_WRITE_SCOPES = (
    *GOOGLE_READONLY_SCOPES,
    "https://www.googleapis.com/auth/calendar.events",
)
GOOGLE_GMAIL_SEND_CALENDAR_WRITE_SCOPES = (
    *GOOGLE_GMAIL_SEND_SCOPES,
    "https://www.googleapis.com/auth/calendar.events",
)
GOOGLE_WRITE_PERMISSION_GMAIL_SEND = "gmail_send"
GOOGLE_WRITE_PERMISSION_GMAIL_MODIFY = "gmail_modify"
GOOGLE_WRITE_PERMISSION_CALENDAR_EVENTS = "calendar_events"
# Backward-compatible names for callers that only need the current default.
GOOGLE_CAPABILITY_BUNDLE = GOOGLE_RECOMMENDED_CAPABILITY_BUNDLE
GOOGLE_REQUESTED_SCOPES = GOOGLE_RECOMMENDED_SCOPES
GOOGLE_SCOPE_PREFIX = "https://www.googleapis.com/auth/"
GOOGLE_MAIL_SCOPE = "https://mail.google.com/"
GOOGLE_CALENDAR_FEEDS_SCOPE = "https://www.google.com/calendar/feeds"
GOOGLE_CONTACTS_FEEDS_SCOPE = "https://www.google.com/m8/feeds"
GOOGLE_EXACT_SCOPE_SERVICES = {
    scope_url: str(disclosure["service"])
    for scope_url, disclosure in COMPATIBILITY_SCOPE_DISCLOSURES_BY_URL.items()
}
GOOGLE_EXACT_SCOPE_LABELS = {
    scope_url: str(disclosure["user_copy"])
    for scope_url, disclosure in COMPATIBILITY_SCOPE_DISCLOSURES_BY_URL.items()
}
GOOGLE_SCOPE_ALIASES = {
    f"{GOOGLE_SCOPE_PREFIX}userinfo.email": "email",
    f"{GOOGLE_SCOPE_PREFIX}userinfo.profile": "profile",
}
GOOGLE_SCOPE_MAX_COUNT = 32
GOOGLE_GRANT_SCOPE_MAX_COUNT = GOOGLE_SCOPE_MAX_COUNT + len(GOOGLE_IDENTITY_SCOPES)
GOOGLE_ACCESS_PAIR_COUNT = 2
GOOGLE_SCOPE_MAX_LENGTH = 512
GOOGLE_SCOPE_TOTAL_MAX_LENGTH = 4096
GOOGLE_REASON_MAX_LENGTH = 280
CONTROL_CODEPOINT_LIMIT = 0x20
DELETE_CODEPOINT = 0x7F
GOOGLE_SERVICE_ORDER = (
    "identity",
    "gmail",
    "calendar",
    "drive",
    "docs",
    "sheets",
    "slides",
    "people",
    "tasks",
    "chat",
    "forms",
    "meet",
    "classroom",
    "keep",
    "apps_script",
    "cloud_search",
    "admin",
    "google",
)
GOOGLE_SERVICE_LABELS = {
    "gmail": "Gmail",
    "calendar": "Calendar",
    "drive": "Drive",
    "docs": "Docs",
    "sheets": "Sheets",
    "slides": "Slides",
    "people": "People and Contacts",
    "tasks": "Tasks",
    "chat": "Chat",
    "forms": "Forms",
    "meet": "Meet",
    "classroom": "Classroom",
    "keep": "Keep",
    "apps_script": "Apps Script",
    "cloud_search": "Cloud Search",
    "admin": "Workspace Admin",
    "google": "other Google services",
}
GOOGLE_AUTHORIZATION_HOST = "accounts.google.com"
GOOGLE_AUTHORIZATION_PATH = "/o/oauth2/v2/auth"
TINYHAT_GOOGLE_PREPARE_PATH = "/hapi/v1/public/tinyhat/google-workspace/oauth/prepare/v1"
DEFAULT_EXPIRES_IN_SECONDS = 600
INSTALL_CLAIM_MAX_ATTEMPTS = 3
INSTALL_CLAIM_RETRY_SECONDS = 1.0
DISCONNECT_WORKER_READY_TIMEOUT_SECONDS = 15.0
DISCONNECT_WORKER_READY_POLL_SECONDS = 0.05
DISCONNECT_COMPLETION_RETRY_SECONDS = 60 * 60
DISCONNECT_COMPLETION_MAX_RETRY_DELAY_SECONDS = 30.0
DISCONNECT_AUTO_RESUME_LIMIT = 8
DISCONNECT_ORPHAN_SWEEP_GRACE_SECONDS = 5 * 60
DISCONNECT_ORPHAN_SWEEP_SCAN_LIMIT = 32
DISCONNECT_ORPHAN_SWEEP_DELETE_LIMIT = 8
INSTALL_RECEIPT_SCAN_LIMIT = 32
CONTEXT_ASSIGNMENT_CHECK_TTL_SECONDS = 30.0
CONTEXT_ASSIGNMENT_CHECK_TIMEOUT_SECONDS = 2
AUTHORIZATION_URL_MAX_LENGTH = 32 * 1024
PUBLIC_CLIENT_ID_MAX_LENGTH = 512
GOOGLE_TOKEN_VALUE_MAX_LENGTH = 16_384
GOOGLE_TOKEN_EXPIRY_MAX_LENGTH = 64
OWNER_ONLY_FILE_MODE = 0o600
HANDOFF_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
GOOGLE_CONNECTION_ID_RE = re.compile(r"^gwo_[A-Za-z0-9_-]{1,60}$")
GOOGLE_LAUNCH_TICKET_MAX_LENGTH = 32 * 1024
GOOGLE_LAUNCH_TICKET_RE = re.compile(
    rf"^gwol1\.[1-9][0-9]{{0,9}}\."
    rf"[A-Za-z0-9_-]{{32,{GOOGLE_LAUNCH_TICKET_MAX_LENGTH}}}$"
)
DISCONNECT_OWNER_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
DISCONNECT_GENERATION_RE = re.compile(r"^[0-9a-f]{64}$")
STATE_DIR = Path.home() / ".tinyhat" / "google-workspace"
CREDENTIALS_PATH = STATE_DIR / "accounts.json"
LEGACY_CREDENTIALS_PATH = STATE_DIR / "credentials.json"
HANDOFFS_DIR = STATE_DIR / "handoffs"
INSTALL_RECEIPTS_DIR = STATE_DIR / "install-receipts"
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
_context_assignment_check_cache: dict[str, tuple[tuple[int, int, int, int, str], float]] = {}
_context_assignment_check_cache_lock = threading.Lock()


class GoogleWorkspaceError(RuntimeError):
    """A Google Workspace connection step failed safely."""


class GoogleWorkspaceAccountSelectionRequired(GoogleWorkspaceError):
    """An account-specific action cannot safely guess among connected accounts."""

    def __init__(self, accounts: list[dict[str, Any]]) -> None:
        self.accounts = accounts
        super().__init__("Choose one connected Google Workspace account.")


class GoogleWorkspaceScopeReviewRequired(GoogleWorkspaceError):
    """A declared or canonical scope is not requestable for this OAuth client."""

    def __init__(self, profile: GoogleWorkspaceProfile) -> None:
        self.profile = profile
        super().__init__("Google Workspace access requires OAuth scope review.")


class GoogleWorkspacePlatformSyncPending(GoogleWorkspaceError):
    """A durable credential-install acknowledgement must settle first."""


class GoogleWorkspacePlatformNotReady(GoogleWorkspaceError):
    """The platform permanently cannot review this OAuth request as deployed."""

    def __init__(self, *, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


@dataclass(frozen=True)
class GoogleWorkspaceProfile:
    """One normalized reviewed or caller-selected OAuth capability request."""

    name: str
    capability_bundle: str
    services: tuple[str, ...]
    scopes: tuple[str, ...]
    access_label: str
    write_permissions: frozenset[str]
    reason: str | None = None
    preset_ids: tuple[str, ...] = ()
    manifest_version: str = str(MANIFEST["manifest_version"])
    client_policy_id: str = GOOGLE_WORKSPACE_PLUGIN_POLICY_FALLBACK
    blocked_scopes: tuple[BlockedScope, ...] = ()
    legacy_profile: bool = False


GOOGLE_LEGACY_PROFILE_CONFIGS = {
    GOOGLE_WORKSPACE_PROFILE_RECOMMENDED: GoogleWorkspaceProfile(
        name=GOOGLE_WORKSPACE_PROFILE_RECOMMENDED,
        capability_bundle=GOOGLE_RECOMMENDED_CAPABILITY_BUNDLE,
        services=GOOGLE_REQUESTED_SERVICES,
        scopes=GOOGLE_RECOMMENDED_SCOPES,
        access_label=(
            "Gmail reading, composing, sending, and inbox/draft/label management while "
            "messages and threads cannot bypass Trash for immediate permanent deletion, "
            "Calendar event management, and "
            "read-only Drive access"
        ),
        write_permissions=frozenset(
            {
                GOOGLE_WRITE_PERMISSION_GMAIL_MODIFY,
                GOOGLE_WRITE_PERMISSION_CALENDAR_EVENTS,
            }
        ),
        legacy_profile=True,
    ),
    GOOGLE_WORKSPACE_PROFILE_READONLY: GoogleWorkspaceProfile(
        name=GOOGLE_WORKSPACE_PROFILE_READONLY,
        capability_bundle=GOOGLE_READONLY_CAPABILITY_BUNDLE,
        services=GOOGLE_REQUESTED_SERVICES,
        scopes=GOOGLE_READONLY_SCOPES,
        access_label="read-only Gmail, Calendar, and Drive access",
        write_permissions=frozenset(),
        legacy_profile=True,
    ),
    GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND: GoogleWorkspaceProfile(
        name=GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND,
        capability_bundle=GOOGLE_GMAIL_SEND_CAPABILITY_BUNDLE,
        services=GOOGLE_REQUESTED_SERVICES,
        scopes=GOOGLE_GMAIL_SEND_SCOPES,
        access_label=("read-only Gmail, Calendar, and Drive access plus permission to send Gmail"),
        write_permissions=frozenset({GOOGLE_WRITE_PERMISSION_GMAIL_SEND}),
        legacy_profile=True,
    ),
    GOOGLE_WORKSPACE_PROFILE_CALENDAR_WRITE: GoogleWorkspaceProfile(
        name=GOOGLE_WORKSPACE_PROFILE_CALENDAR_WRITE,
        capability_bundle=GOOGLE_CALENDAR_WRITE_CAPABILITY_BUNDLE,
        services=GOOGLE_REQUESTED_SERVICES,
        scopes=GOOGLE_CALENDAR_WRITE_SCOPES,
        access_label=(
            "read-only Gmail, Calendar, and Drive access plus permission to create, "
            "update, and delete Calendar events"
        ),
        write_permissions=frozenset({GOOGLE_WRITE_PERMISSION_CALENDAR_EVENTS}),
        legacy_profile=True,
    ),
    GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND_CALENDAR_WRITE: GoogleWorkspaceProfile(
        name=GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND_CALENDAR_WRITE,
        capability_bundle=GOOGLE_GMAIL_SEND_CALENDAR_WRITE_CAPABILITY_BUNDLE,
        services=GOOGLE_REQUESTED_SERVICES,
        scopes=GOOGLE_GMAIL_SEND_CALENDAR_WRITE_SCOPES,
        access_label=(
            "read-only Gmail, Calendar, and Drive access plus permission to send Gmail "
            "and create, update, and delete Calendar events"
        ),
        write_permissions=frozenset(
            {
                GOOGLE_WRITE_PERMISSION_GMAIL_SEND,
                GOOGLE_WRITE_PERMISSION_CALENDAR_EVENTS,
            }
        ),
        legacy_profile=True,
    ),
}


def _write_permissions_for_capabilities(
    capabilities: tuple[str, ...],
) -> frozenset[str]:
    permissions: set[str] = set()
    if "gmail_inbox_management" in capabilities:
        permissions.add(GOOGLE_WRITE_PERMISSION_GMAIL_MODIFY)
    elif "gmail_send" in capabilities:
        permissions.add(GOOGLE_WRITE_PERMISSION_GMAIL_SEND)
    if "calendar_event_write" in capabilities:
        permissions.add(GOOGLE_WRITE_PERMISSION_CALENDAR_EVENTS)
    if any(
        capability
        in {
            "drive_file_collaboration",
            "gmail_drafts",
            "gmail_label_definitions",
            "tasks_management",
        }
        for capability in capabilities
    ):
        permissions.add("custom")
    return frozenset(permissions)


def _profile_from_scope_resolution(
    resolution: ScopeResolution,
    *,
    reason: str | None = None,
    client_policy_id: str,
) -> GoogleWorkspaceProfile:
    if not resolution.selected_preset_ids and resolution.bundle_id == IDENTITY_BUNDLE_ID:
        name = GOOGLE_WORKSPACE_PROFILE_IDENTITY
    elif (
        len(resolution.selected_preset_ids) == 1
        and resolution.bundle_id != GOOGLE_CUSTOM_CAPABILITY_BUNDLE
    ):
        name = resolution.selected_preset_ids[0]
    else:
        name = GOOGLE_WORKSPACE_PROFILE_CUSTOM
    access_label = (
        f"Google permissions needed to {reason}" if reason is not None else resolution.access_label
    )
    return GoogleWorkspaceProfile(
        name=name,
        capability_bundle=resolution.bundle_id,
        services=resolution.services,
        scopes=resolution.scope_urls,
        access_label=access_label,
        write_permissions=_write_permissions_for_capabilities(resolution.capabilities),
        reason=reason,
        preset_ids=resolution.selected_preset_ids,
        client_policy_id=client_policy_id,
        blocked_scopes=resolution.blocked,
    )


GOOGLE_CURRENT_PROFILE_CONFIGS = {
    GOOGLE_WORKSPACE_PROFILE_IDENTITY: _profile_from_scope_resolution(
        resolve_scope_request(client_policy_id="tinyhat-development"),
        client_policy_id="tinyhat-development",
    ),
    **{
        preset_id: _profile_from_scope_resolution(
            resolve_scope_request(
                preset_ids=(preset_id,),
                client_policy_id="tinyhat-development",
            ),
            client_policy_id="tinyhat-development",
        )
        for preset_id in GOOGLE_WORKSPACE_PRESETS
    },
}
GOOGLE_PROFILE_CONFIGS = {
    **GOOGLE_LEGACY_PROFILE_CONFIGS,
    **GOOGLE_CURRENT_PROFILE_CONFIGS,
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
    connection_action: str
    target_connection_id: str | None


@dataclass(frozen=True)
class GoogleWorkspaceDisconnectIntent:
    """One platform-owned disconnect ceremony polled by this Computer."""

    client: PlatformClient
    platform_auth: str
    intent_id: str
    owner_token: str
    connection_id: str
    credential_generation: str
    expires_at: str
    poll_after_ms: int


@dataclass(frozen=True)
class GoogleWorkspaceDisconnectCompletionReceipt:
    """Durable proof that polling must resume completion without another delete."""

    phase: str
    outcome: str
    error_code: str | None


def google_workspace(  # noqa: PLR0911, PLR0912
    args: dict[str, Any] | None = None, **_: Any
) -> str:
    """Connect, inspect, change, or disconnect this Computer's Google accounts."""
    payload = args if isinstance(args, dict) else {}
    raw_action = payload.get("action")
    if not isinstance(raw_action, str) or not raw_action.strip():
        return tool_error_json(
            tool="tinyhat_google_workspace",
            error_name="missing_required_parameter",
            message=(
                "Call tinyhat_google_workspace with action='connect', "
                "action='status', action='set_permissions', or action='disconnect'."
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

    # Connect and permission changes perform this recovery only after the
    # platform has approved their exact final scope set. That ordering keeps a
    # review-required response completely side-effect free. Other actions keep
    # the normal opportunistic recovery behavior.
    if action not in {"connect", "set_permissions"}:
        with contextlib.suppress(Exception):
            _resume_retained_install_receipts()
        with contextlib.suppress(Exception):
            _resume_retained_disconnect_workers()

    raw_profile = payload.get("profile")
    raw_presets = payload.get("presets")
    raw_scopes = payload.get("scopes")
    raw_reason = payload.get("reason")
    if action not in {"connect", "set_permissions"} and any(
        item is not None for item in (raw_profile, raw_presets, raw_scopes, raw_reason)
    ):
        return tool_error_json(
            tool="tinyhat_google_workspace",
            error_name="invalid_parameter",
            message=(
                "The profile, presets, scopes, and reason parameters are accepted only with "
                "action='connect' or action='set_permissions'."
            ),
            expected={
                "profile": list(GOOGLE_WORKSPACE_PROFILES),
                "presets": list(GOOGLE_WORKSPACE_PRESETS),
                "scopes": "canonical manifest-listed Google OAuth scopes",
                "reason": "short user-facing reason required with scopes",
            },
            example_call={"action": "connect"},
        )

    try:
        account_id = _optional_account_id(payload.get("account_id"))
    except GoogleWorkspaceError:
        return tool_error_json(
            tool="tinyhat_google_workspace",
            error_name="invalid_parameter",
            message="Google Workspace account_id is invalid.",
            expected={"account_id": "opaque account_id returned by status"},
            example_call={"action": "status"},
        )

    if action == "set_permissions" and account_id is None:
        return tool_error_json(
            tool="tinyhat_google_workspace",
            error_name="missing_required_parameter",
            message="Choose the Google Workspace account whose permissions should change.",
            missing=["account_id"],
            expected={"account_id": "opaque account_id returned by status"},
            example_call={
                "action": "set_permissions",
                "account_id": "connection_id_from_status",
                "presets": [GOOGLE_WORKSPACE_PROFILE_INBOX_MANAGER],
            },
        )

    if action == "status":
        try:
            result = _status_payload(account_id=account_id)
        except GoogleWorkspaceAccountSelectionRequired as exc:
            return _account_selection_error(
                tool="tinyhat_google_workspace",
                action="status",
                accounts=exc.accounts,
            )
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
            result = _start_disconnect_intent(account_id=account_id)
        except GoogleWorkspaceAccountSelectionRequired as exc:
            return _account_selection_error(
                tool="tinyhat_google_workspace",
                action="disconnect",
                accounts=exc.accounts,
            )
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
            profile = _requested_profile(
                raw_profile,
                presets=raw_presets,
                scopes=raw_scopes,
                reason=raw_reason,
                require_selection=action == "set_permissions",
            )
        except GoogleWorkspaceError as exc:
            return tool_error_json(
                tool="tinyhat_google_workspace",
                error_name="invalid_parameter",
                message=str(exc),
                expected={
                    "profile": list(GOOGLE_WORKSPACE_PROFILES),
                    "or": {
                        "presets": list(GOOGLE_WORKSPACE_PRESETS),
                        "scopes": "canonical manifest-listed Google OAuth scopes",
                        "reason": "short explanation shown before Google consent",
                    },
                },
                example_call={
                    "action": "connect",
                    "presets": [GOOGLE_WORKSPACE_PROFILE_INBOX_MANAGER],
                },
            )
        try:
            result = _start_connection(
                profile=profile,
                account_id=account_id,
                exact_permissions=action == "set_permissions",
            )
        except GoogleWorkspaceScopeReviewRequired as exc:
            result = _scope_review_required_payload(
                profile=exc.profile,
                action=action,
            )
        except GoogleWorkspacePlatformSyncPending:
            return tool_error_json(
                tool="tinyhat_google_workspace",
                error_name="platform_sync_pending",
                message=(
                    "A saved Google connection is still syncing safe metadata with "
                    "Tinyhat. Retry this permission or connection change shortly."
                ),
                example_call={"action": "status"},
            )
        except GoogleWorkspacePlatformNotReady as exc:
            result = {
                "schema": "tinyhat_google_workspace_action_v1",
                "action": action,
                "status": "platform_not_ready",
                "button_sent": False,
                "error_code": exc.error_code,
                "message": str(exc),
            }
        except GoogleWorkspaceAccountSelectionRequired as exc:
            return _account_selection_error(
                tool="tinyhat_google_workspace",
                action=action,
                accounts=exc.accounts,
            )
        except Exception:
            result = {
                "schema": "tinyhat_google_workspace_action_v1",
                "action": action,
                "status": "failed",
                "message": ("I could not start Google sign-in on this Computer. Please try again."),
            }
    return json.dumps(result, sort_keys=True)


def _optional_account_id(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GoogleWorkspaceError("Google Workspace account id must be a string.")
    account_id = value.strip()
    if GOOGLE_CONNECTION_ID_RE.fullmatch(account_id) is None:
        raise GoogleWorkspaceError("Google Workspace account id is invalid.")
    return account_id


def _account_selection_error(*, tool: str, action: str, accounts: list[dict[str, Any]]) -> str:
    return tool_error_json(
        tool=tool,
        error_name="account_selection_required",
        message=(
            "More than one Google Workspace account is connected. Choose the exact "
            "account_id from this safe account list and retry."
        ),
        expected={"accounts": accounts},
        example_call={"action": action, "account_id": accounts[0]["account_id"]},
    )


def _validated_scope_values(
    value: Any,
    *,
    completed_grant: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise GoogleWorkspaceError("Google Workspace scopes must be a non-empty bounded list.")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        canonical_item = _canonical_scope_item(item)
        if canonical_item in seen:
            raise GoogleWorkspaceError("Google Workspace scopes cannot contain duplicates.")
        seen.add(canonical_item)
        normalized.append(canonical_item)
    bounded_scopes = (
        [scope for scope in normalized if scope not in GOOGLE_IDENTITY_SCOPES]
        if completed_grant
        else normalized
    )
    if completed_grant and len(normalized) > GOOGLE_GRANT_SCOPE_MAX_COUNT:
        raise GoogleWorkspaceError("Google Workspace completed grant is too large.")
    if len(bounded_scopes) > GOOGLE_SCOPE_MAX_COUNT:
        raise GoogleWorkspaceError(
            "Google Workspace scopes may contain at most 32 requested permissions."
        )
    if sum(len(scope.encode("utf-8")) for scope in bounded_scopes) > GOOGLE_SCOPE_TOTAL_MAX_LENGTH:
        raise GoogleWorkspaceError("Google Workspace scopes are too large.")
    return tuple(normalized)


def _canonical_scope_item(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise GoogleWorkspaceError("Google Workspace scopes must be canonical strings.")
    if not value.isascii() or len(value.encode("utf-8")) > GOOGLE_SCOPE_MAX_LENGTH:
        raise GoogleWorkspaceError("Google Workspace scope is too long.")
    if any(
        character.isspace()
        or ord(character) < CONTROL_CODEPOINT_LIMIT
        or ord(character) == DELETE_CODEPOINT
        for character in value
    ):
        raise GoogleWorkspaceError("Google Workspace scopes cannot contain whitespace or controls.")
    canonical = GOOGLE_SCOPE_ALIASES.get(value, value)
    legacy_aliases = {
        f"{GOOGLE_CALENDAR_FEEDS_SCOPE}/",
        f"{GOOGLE_CONTACTS_FEEDS_SCOPE}/",
    }
    if canonical in legacy_aliases:
        canonical = canonical.removesuffix("/")
    if (
        canonical in GOOGLE_IDENTITY_SCOPES
        or canonical == GOOGLE_MAIL_SCOPE
        or canonical in GOOGLE_EXACT_SCOPE_SERVICES
    ):
        return canonical
    if not canonical.startswith(GOOGLE_SCOPE_PREFIX):
        raise GoogleWorkspaceError("Google Workspace scope is not owned by Google.")
    suffix = canonical[len(GOOGLE_SCOPE_PREFIX) :]
    if (
        not suffix
        or suffix.startswith((".", "/"))
        or suffix.endswith((".", "/"))
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/"
            for character in suffix
        )
    ):
        raise GoogleWorkspaceError("Google Workspace scope is not canonical.")
    return canonical


def _canonical_requested_scopes(value: Any) -> tuple[str, ...]:
    requested = _validated_scope_values(value)
    non_identity = sorted(scope for scope in requested if scope not in GOOGLE_IDENTITY_SCOPES)
    return _validated_scope_values(
        [*GOOGLE_IDENTITY_SCOPES, *non_identity],
        completed_grant=True,
    )


def _canonical_custom_grant_scopes(value: Any) -> tuple[str, ...]:
    scopes = _validated_scope_values(value, completed_grant=True)
    if not set(GOOGLE_IDENTITY_SCOPES).issubset(scopes):
        raise GoogleWorkspaceError("Google Workspace custom scopes are missing basic identity.")
    try:
        # Stored custom grants are historical evidence, not new requests.
        # Preserve their exact canonical scope order and redundant atoms so
        # status and refresh continue to match the grant Google issued.
        return legacy_scope_urls(
            GOOGLE_CUSTOM_CAPABILITY_BUNDLE,
            saved_scope_urls=scopes,
        )
    except ValueError as exc:
        raise GoogleWorkspaceError(str(exc)) from exc


def _validated_scope_reason(value: Any, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise GoogleWorkspaceError("Google Workspace permission reason must be a string.")
    reason = value.strip()
    if (
        not reason
        or len(reason) > GOOGLE_REASON_MAX_LENGTH
        or any(
            ord(character) < CONTROL_CODEPOINT_LIMIT or ord(character) == DELETE_CODEPOINT
            for character in reason
        )
    ):
        raise GoogleWorkspaceError("Google Workspace permission reason is invalid.")
    return reason


def _scope_service(scope: str) -> str | None:
    if scope in GOOGLE_IDENTITY_SCOPES:
        return None
    manifest_scope = SCOPES_BY_URL.get(scope)
    if manifest_scope is not None:
        return str(manifest_scope["service"])
    if scope in GOOGLE_EXACT_SCOPE_SERVICES:
        return GOOGLE_EXACT_SCOPE_SERVICES[scope]
    suffix = scope[len(GOOGLE_SCOPE_PREFIX) :]
    mappings = (
        (("gmail",), "gmail"),
        (("calendar",), "calendar"),
        (("drive",), "drive"),
        (("documents",), "docs"),
        (("spreadsheets",), "sheets"),
        (("presentations",), "slides"),
        (("contacts", "directory", "user."), "people"),
        (("tasks",), "tasks"),
        (("chat",), "chat"),
        (("forms",), "forms"),
        (("meetings",), "meet"),
        (("classroom",), "classroom"),
        (("keep",), "keep"),
        (("script",), "apps_script"),
        (("cloud_search",), "cloud_search"),
        (("admin.", "apps.groups.settings"), "admin"),
    )
    for prefixes, service in mappings:
        if suffix.startswith(prefixes):
            return service
    return "google"


def _services_for_scopes(scopes: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    services_by_scope = tuple(
        service for scope in scopes if (service := _scope_service(scope)) is not None
    )
    present = {"identity", *services_by_scope}
    ordered = [service for service in GOOGLE_SERVICE_ORDER if service in present]
    ordered.extend(
        dict.fromkeys(
            service for service in services_by_scope if service not in GOOGLE_SERVICE_ORDER
        )
    )
    return tuple(ordered)


def _google_access_label(service_labels: list[str]) -> str:
    if not service_labels:
        return "Google identity access"
    if len(service_labels) == 1:
        joined = service_labels[0]
    elif len(service_labels) == GOOGLE_ACCESS_PAIR_COUNT:
        joined = f"{service_labels[0]} and {service_labels[1]}"
    else:
        joined = f"{', '.join(service_labels[:-1])}, and {service_labels[-1]}"
    return f"Google access for {joined}"


def _custom_profile(
    scopes: Any,
    *,
    reason: str | None = None,
) -> GoogleWorkspaceProfile:
    canonical_scopes = _canonical_custom_grant_scopes(scopes)
    canonical_services = _services_for_scopes(canonical_scopes)
    exact_scope_labels = [
        GOOGLE_EXACT_SCOPE_LABELS[scope]
        for scope in canonical_scopes
        if scope in GOOGLE_EXACT_SCOPE_LABELS
    ]
    service_labels = [
        GOOGLE_SERVICE_LABELS.get(service, service.replace("_", " ").title())
        for service in canonical_services
        if service != "identity"
    ]
    access_label = (
        f"Google permissions needed to {reason}" if reason else _google_access_label(service_labels)
    )
    if exact_scope_labels:
        access_label = f"{access_label}: {'; '.join(exact_scope_labels)}"
    return GoogleWorkspaceProfile(
        name=GOOGLE_WORKSPACE_PROFILE_CUSTOM,
        capability_bundle=GOOGLE_CUSTOM_CAPABILITY_BUNDLE,
        services=canonical_services,
        scopes=canonical_scopes,
        access_label=access_label,
        write_permissions=frozenset({"custom"}),
        reason=reason,
    )


def _selected_client_policy_id() -> str:
    policy_id = os.environ.get(
        "TINYHAT_GOOGLE_WORKSPACE_CLIENT_POLICY_ID",
        GOOGLE_WORKSPACE_PLUGIN_POLICY_FALLBACK,
    ).strip()
    if not policy_id:
        policy_id = GOOGLE_WORKSPACE_PLUGIN_POLICY_FALLBACK
    if policy_id not in CLIENT_POLICIES_BY_ID:
        raise GoogleWorkspaceError("Google Workspace OAuth scope policy is not configured safely.")
    return policy_id


def _validated_preset_ids(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not value:
        raise GoogleWorkspaceError("Google Workspace presets must be a non-empty list.")
    if len(value) > len(GOOGLE_WORKSPACE_PRESETS):
        raise GoogleWorkspaceError("Google Workspace preset selection is too large.")
    if any(not isinstance(item, str) or item != item.strip() for item in value):
        raise GoogleWorkspaceError("Google Workspace preset ids must be strings.")
    preset_ids = tuple(value)
    if len(preset_ids) != len(set(preset_ids)):
        raise GoogleWorkspaceError("Google Workspace presets cannot contain duplicates.")
    unknown = sorted(set(preset_ids) - set(GOOGLE_WORKSPACE_PRESETS))
    if unknown:
        raise GoogleWorkspaceError(f"Unknown Google Workspace presets: {', '.join(unknown)}.")
    return preset_ids


def _requested_profile(
    value: Any,
    *,
    presets: Any = None,
    scopes: Any = None,
    reason: Any = None,
    require_selection: bool = False,
) -> GoogleWorkspaceProfile:
    if value is not None and any(item is not None for item in (presets, scopes, reason)):
        raise GoogleWorkspaceError(
            "A legacy Google Workspace profile cannot be combined with presets, scopes, or reason."
        )
    client_policy_id = _selected_client_policy_id()
    if value is not None:
        if not isinstance(value, str):
            raise GoogleWorkspaceError("Google Workspace profile must be a string.")
        legacy = GOOGLE_LEGACY_PROFILE_CONFIGS.get(value.strip().lower())
        if legacy is None:
            raise GoogleWorkspaceError("Google Workspace profile is not allowlisted.")
        return GoogleWorkspaceProfile(
            name=legacy.name,
            capability_bundle=legacy.capability_bundle,
            services=legacy.services,
            scopes=legacy.scopes,
            access_label=legacy.access_label,
            write_permissions=legacy.write_permissions,
            manifest_version=legacy.manifest_version,
            client_policy_id=client_policy_id,
            blocked_scopes=blocked_scope_details(
                legacy.scopes,
                client_policy_id=client_policy_id,
            ),
            legacy_profile=True,
        )

    preset_ids = _validated_preset_ids(presets)
    if scopes is None:
        if reason is not None:
            raise GoogleWorkspaceError("A Google Workspace reason requires scopes.")
        requested_scope_urls: tuple[str, ...] = ()
        clean_reason = None
    else:
        requested_scope_urls = _validated_scope_values(scopes)
        clean_reason = _validated_scope_reason(reason, required=True)
    if require_selection and not preset_ids and not requested_scope_urls:
        raise GoogleWorkspaceError("set_permissions requires presets, scopes, or a legacy profile.")
    try:
        resolution = resolve_scope_request(
            preset_ids=preset_ids,
            scope_urls=requested_scope_urls,
            client_policy_id=client_policy_id,
        )
    except ValueError as exc:
        raise GoogleWorkspaceError(str(exc)) from exc
    return _profile_from_scope_resolution(
        resolution,
        reason=clean_reason,
        client_policy_id=client_policy_id,
    )


def _scope_review_required_payload(
    *,
    profile: GoogleWorkspaceProfile,
    action: str,
) -> dict[str, Any]:
    blocked: list[dict[str, Any]] = []
    for item in profile.blocked_scopes:
        disclosure = GOOGLE_EXACT_SCOPE_LABELS.get(item.scope_url)
        blocked.append(
            {
                "scope": item.scope_url,
                "scope_id": item.scope_id,
                "display_name": disclosure or item.display_name,
                "request_state": item.request_state,
                "verification_state": item.verification_state,
                "reason": (f"{disclosure}. {item.reason}" if disclosure else item.reason),
            }
        )
    if profile.legacy_profile:
        blocked.append(
            {
                "scope": None,
                "scope_id": None,
                "display_name": "Historical permission profile",
                "request_state": "legacy_only",
                "verification_state": "not_requestable",
                "reason": (
                    "This profile id is retained for historical saved grants. "
                    "Choose current presets or manifest-listed Custom scopes."
                ),
            }
        )
    return {
        "schema": "tinyhat_google_workspace_action_v1",
        "action": action,
        "status": "review_required",
        "button_sent": False,
        "profile": profile.name,
        "presets": list(profile.preset_ids),
        "capability_bundle": profile.capability_bundle,
        "services": list(profile.services),
        "scopes": list(profile.scopes),
        "manifest_version": profile.manifest_version,
        "client_policy_id": profile.client_policy_id,
        "blocked_scopes": blocked,
        "message": (
            "Tinyhat did not start Google authorization because this exact access "
            "is not approved for the selected OAuth client. Choose a narrower "
            "reviewed preset or manifest-listed scope, or complete the product and "
            "Google review before trying again."
        ),
    }


def _platform_review_required_profile(
    profile: GoogleWorkspaceProfile,
    exc: PlatformError,
) -> GoogleWorkspaceProfile | None:
    if exc.status_code != HTTP_FORBIDDEN or not isinstance(exc.response, dict):
        return None
    detail = exc.response.get("detail")
    if not isinstance(detail, dict) or detail.get("error_code") != "review_required":
        return None
    manifest_version = detail.get("scope_manifest_version")
    client_policy_id = detail.get("client_policy_id")
    capability_bundle = detail.get("capability_bundle")
    raw_blocked = detail.get("blocked_scopes")
    if (
        not isinstance(manifest_version, str)
        or not isinstance(client_policy_id, str)
        or client_policy_id not in CLIENT_POLICIES_BY_ID
        or capability_bundle != profile.capability_bundle
        or not isinstance(raw_blocked, list)
        or not raw_blocked
    ):
        return None
    blocked: list[BlockedScope] = []
    for item in raw_blocked:
        if not isinstance(item, dict):
            return None
        scope_url = item.get("scope")
        scope_id = item.get("scope_id")
        values = {
            key: item.get(key)
            for key in (
                "display_name",
                "request_state",
                "verification_state",
                "reason",
            )
        }
        if (
            not isinstance(scope_url, str)
            or (scope_id is not None and not isinstance(scope_id, str))
            or any(not isinstance(value, str) for value in values.values())
        ):
            return None
        blocked.append(
            BlockedScope(
                scope_url=scope_url,
                scope_id=scope_id,
                display_name=values["display_name"],
                request_state=values["request_state"],
                verification_state=values["verification_state"],
                reason=values["reason"],
            )
        )
    return GoogleWorkspaceProfile(
        name=profile.name,
        capability_bundle=profile.capability_bundle,
        services=profile.services,
        scopes=profile.scopes,
        access_label=profile.access_label,
        write_permissions=profile.write_permissions,
        reason=profile.reason,
        preset_ids=profile.preset_ids,
        manifest_version=manifest_version,
        client_policy_id=client_policy_id,
        blocked_scopes=tuple(blocked),
        legacy_profile=profile.legacy_profile,
    )


def _malformed_platform_review_error(
    exc: PlatformError,
) -> GoogleWorkspacePlatformNotReady | None:
    """Explain a declared review rejection that cannot be trusted or retried."""

    if exc.status_code != HTTP_FORBIDDEN or not isinstance(exc.response, dict):
        return None
    detail = exc.response.get("detail")
    if not isinstance(detail, dict) or detail.get("error_code") != "review_required":
        return None
    return GoogleWorkspacePlatformNotReady(
        error_code="invalid_scope_review_response",
        message=(
            "Google sign-in was rejected by the Tinyhat platform, but its "
            "permission-review response was incomplete or invalid. The platform "
            "and plugin must be brought to a compatible policy version before this "
            "request can start; retrying the same request will not help."
        ),
    )


def _profile_with_authoritative_policy(
    profile: GoogleWorkspaceProfile,
    *,
    manifest_version: str,
    client_policy_id: str,
) -> GoogleWorkspaceProfile:
    """Attach the platform's reviewed policy stamp without changing access."""
    return GoogleWorkspaceProfile(
        name=profile.name,
        capability_bundle=profile.capability_bundle,
        services=profile.services,
        scopes=profile.scopes,
        access_label=profile.access_label,
        write_permissions=profile.write_permissions,
        reason=profile.reason,
        preset_ids=profile.preset_ids,
        manifest_version=manifest_version,
        client_policy_id=client_policy_id,
        blocked_scopes=profile.blocked_scopes,
        legacy_profile=profile.legacy_profile,
    )


def _profile_for_capability_bundle(
    value: Any,
    *,
    scopes: Any = None,
    services: Any = None,
) -> GoogleWorkspaceProfile:
    if value == GOOGLE_CUSTOM_CAPABILITY_BUNDLE:
        # Scopes are the authority. Service names are a derived display/index
        # projection and may evolve independently across platform/plugin versions.
        return _custom_profile(scopes)
    for profile in GOOGLE_PROFILE_CONFIGS.values():
        if value == profile.capability_bundle:
            if scopes is not None and scopes != list(profile.scopes):
                raise GoogleWorkspaceError("Platform returned unexpected Google Workspace scopes.")
            if services is not None and services != list(profile.services):
                raise GoogleWorkspaceError("Platform returned unexpected Google services.")
            return profile
    raise GoogleWorkspaceError("Platform returned an unexpected capability bundle.")


def _profile_for_scope_set(
    scopes: tuple[str, ...] | list[str],
    *,
    force_custom: bool,
    reason: str | None = None,
    client_policy_id: str,
) -> GoogleWorkspaceProfile:
    validated = _validated_scope_values(list(scopes), completed_grant=True)
    if not set(GOOGLE_IDENTITY_SCOPES).issubset(validated):
        raise GoogleWorkspaceError("Google Workspace scopes are missing basic identity.")
    try:
        normalized = normalize_scope_urls(validated)
    except ValueError as exc:
        raise GoogleWorkspaceError(str(exc)) from exc
    if not force_custom:
        for profile_id, profile in GOOGLE_CURRENT_PROFILE_CONFIGS.items():
            if set(normalized) != set(profile.scopes):
                continue
            if profile_id == GOOGLE_WORKSPACE_PROFILE_IDENTITY:
                resolution = resolve_scope_request(client_policy_id=client_policy_id)
            else:
                resolution = resolve_scope_request(
                    preset_ids=(profile_id,),
                    client_policy_id=client_policy_id,
                )
            return _profile_from_scope_resolution(
                resolution,
                reason=reason,
                client_policy_id=client_policy_id,
            )
    resolution = resolve_scope_request(
        scope_urls=normalized,
        client_policy_id=client_policy_id,
    )
    return _profile_from_scope_resolution(
        resolution,
        reason=reason,
        client_policy_id=client_policy_id,
    )


def _resolve_profile_for_connection_locked(
    requested_profile: GoogleWorkspaceProfile,
    *,
    account_id: str | None = None,
    exact_permissions: bool = False,
    client: PlatformClient | None = None,
    platform_auth: str | None = None,
) -> tuple[GoogleWorkspaceProfile, PlatformClient | None, str | None]:
    """Resolve one assignment-verified add or exact target before side effects."""
    current_credentials: dict[str, Any] | None = None
    if (client is None) != (platform_auth is None):
        raise GoogleWorkspaceError("Google Workspace platform authentication is incomplete.")
    current_scopes: tuple[str, ...] = GOOGLE_IDENTITY_SCOPES
    current_bundle: str | None = None
    if account_id is not None:
        if client is None or platform_auth is None:
            client, platform_auth = build_platform_client()
        _migrate_legacy_credentials_locked(
            client=client,
            platform_auth=platform_auth,
        )
        current_credentials = _read_credentials(account_id)
        if current_credentials is None:
            raise GoogleWorkspaceError("Google Workspace account is not connected.")
        if not _assignment_binding_matches_platform(
            credentials=current_credentials,
            client=client,
            platform_auth=platform_auth,
        ):
            ACTIVE_DISCONNECT_PATH.unlink(missing_ok=True)
            _cancel_all_pending_handoffs_locked()
            _delete_credentials_locked()
            raise GoogleWorkspaceError("Computer assignment changed before Google sign-in.")
        else:
            current_scopes = tuple(current_credentials["scopes"])
            current_bundle = str(current_credentials["capability_bundle"])
    elif CREDENTIALS_PATH.exists() or _owner_entry_exists(LEGACY_CREDENTIALS_PATH):
        if client is None or platform_auth is None:
            client, platform_auth = build_platform_client()
        _migrate_legacy_credentials_locked(
            client=client,
            platform_auth=platform_auth,
        )
        existing_accounts = _read_account_store()
        if existing_accounts:
            current_binding = _fetch_assignment_binding(
                client=client,
                platform_auth=platform_auth,
            )
            if any(
                not hmac.compare_digest(
                    str(existing["tinyhat_assignment_binding"]),
                    current_binding,
                )
                for existing in existing_accounts
            ):
                ACTIVE_DISCONNECT_PATH.unlink(missing_ok=True)
                _cancel_all_pending_handoffs_locked()
                _delete_credentials_locked()
                _delete_all_install_receipts_locked()
                raise GoogleWorkspaceError("Computer assignment changed before Google sign-in.")

    target_scope_set = set(requested_profile.scopes)
    if not exact_permissions and account_id is not None:
        target_scope_set.update(current_scopes)
    force_custom = requested_profile.capability_bundle == GOOGLE_CUSTOM_CAPABILITY_BUNDLE or (
        not exact_permissions and current_bundle == GOOGLE_CUSTOM_CAPABILITY_BUNDLE
    )
    target_profile = _profile_for_scope_set(
        tuple(target_scope_set),
        force_custom=force_custom,
        reason=requested_profile.reason,
        client_policy_id=requested_profile.client_policy_id,
    )
    return target_profile, client, platform_auth


def _resolve_profile_for_connection_read_only(
    requested_profile: GoogleWorkspaceProfile,
    *,
    account_id: str | None = None,
    exact_permissions: bool = False,
) -> GoogleWorkspaceProfile:
    """Resolve the final request without changing files or calling the platform."""
    current_scopes: tuple[str, ...] = GOOGLE_IDENTITY_SCOPES
    current_bundle: str | None = None
    if account_id is not None:
        current_credentials = _read_credentials(account_id)
        if current_credentials is None:
            # A singleton grant predates opaque connection ids. It is still the
            # only possible additive target; the locked migration later proves
            # the exact platform connection before changing custody.
            current_credentials = _read_legacy_credentials()
        if current_credentials is None:
            raise GoogleWorkspaceError("Google Workspace account is not connected.")
        current_scopes = tuple(current_credentials["scopes"])
        current_bundle = str(current_credentials["capability_bundle"])

    target_scope_set = set(requested_profile.scopes)
    if not exact_permissions and account_id is not None:
        target_scope_set.update(current_scopes)
    force_custom = requested_profile.capability_bundle == GOOGLE_CUSTOM_CAPABILITY_BUNDLE or (
        not exact_permissions and current_bundle == GOOGLE_CUSTOM_CAPABILITY_BUNDLE
    )
    return _profile_for_scope_set(
        tuple(target_scope_set),
        force_custom=force_custom,
        reason=requested_profile.reason,
        client_policy_id=requested_profile.client_policy_id,
    )


def _same_scope_request(
    left: GoogleWorkspaceProfile,
    right: GoogleWorkspaceProfile,
) -> bool:
    return bool(
        left.capability_bundle == right.capability_bundle
        and left.services == right.services
        and left.scopes == right.scopes
    )


def _preflight_connection_request(
    profile: GoogleWorkspaceProfile,
) -> tuple[GoogleWorkspaceProfile, PlatformClient, str]:
    """Ask the attested platform to review one exact request without side effects."""
    client, platform_auth = build_platform_client()
    try:
        response = client.post_json(
            computer_api_path(platform_auth, GOOGLE_WORKSPACE_PREFLIGHT_SUFFIX),
            {
                "capability_bundle": profile.capability_bundle,
                "requested_services": list(profile.services),
                "requested_scopes": list(profile.scopes),
            },
        )
    except PlatformError as exc:
        blocked_profile = _platform_review_required_profile(profile, exc)
        if blocked_profile is not None:
            raise GoogleWorkspaceScopeReviewRequired(blocked_profile) from exc
        malformed_review = _malformed_platform_review_error(exc)
        if malformed_review is not None:
            raise malformed_review from exc
        if exc.status_code == HTTP_NOT_FOUND:
            raise GoogleWorkspacePlatformNotReady(
                error_code="scope_preflight_unavailable",
                message=(
                    "Google sign-in is not available because this Tinyhat platform "
                    "does not provide the required permission-review endpoint. Deploy "
                    "the compatible platform before starting this request; retrying "
                    "the same request will not help."
                ),
            ) from exc
        raise

    _validated_capability_bundle(
        response.get("capability_bundle"),
        expected=profile.capability_bundle,
    )
    if response.get("services") != list(profile.services):
        raise GoogleWorkspaceError("Platform preflight returned unexpected Google services.")
    if response.get("scopes") != list(profile.scopes):
        raise GoogleWorkspaceError("Platform preflight returned unexpected Google scopes.")
    manifest_version = response.get("scope_manifest_version")
    client_policy_id = response.get("client_policy_id")
    if not isinstance(manifest_version, str) or not manifest_version.strip():
        raise GoogleWorkspaceError("Platform preflight did not identify its scope manifest.")
    if not isinstance(client_policy_id, str) or client_policy_id not in CLIENT_POLICIES_BY_ID:
        raise GoogleWorkspaceError("Platform preflight returned an unknown OAuth client policy.")
    return (
        _profile_with_authoritative_policy(
            profile,
            manifest_version=manifest_version,
            client_policy_id=client_policy_id,
        ),
        client,
        platform_auth,
    )


def _start_connection(  # noqa: PLR0912, PLR0915
    *,
    profile: GoogleWorkspaceProfile | None = None,
    account_id: str | None = None,
    exact_permissions: bool = False,
) -> dict[str, Any]:
    if exact_permissions and account_id is None:
        raise GoogleWorkspaceError("Exact Google permission changes require an account id.")
    base_profile = profile or _requested_profile(None)
    if base_profile.legacy_profile or base_profile.blocked_scopes:
        raise GoogleWorkspaceScopeReviewRequired(base_profile)
    requested_profile = _resolve_profile_for_connection_read_only(
        base_profile,
        account_id=account_id,
        exact_permissions=exact_permissions,
    )
    if requested_profile.legacy_profile or requested_profile.blocked_scopes:
        raise GoogleWorkspaceScopeReviewRequired(requested_profile)
    requested_profile, client, platform_auth = _preflight_connection_request(requested_profile)
    authoritative_manifest_version = requested_profile.manifest_version
    authoritative_client_policy_id = requested_profile.client_policy_id

    # Recovery can delete or rewrite durable local state. Run it only after the
    # exact final request has passed the side-effect-free platform review.
    with contextlib.suppress(Exception):
        _resume_retained_install_receipts()
    with contextlib.suppress(Exception):
        _resume_retained_disconnect_workers()

    # Serialize the complete start transition. A disconnect that begins after
    # this connect waits until its marker exists, then cancels it. A second
    # connect supersedes the first marker before either worker may install.
    with _lifecycle_lock():
        current_target = _resolve_profile_for_connection_read_only(
            base_profile,
            account_id=account_id,
            exact_permissions=exact_permissions,
        )
        if not _same_scope_request(current_target, requested_profile):
            raise GoogleWorkspaceError(
                "Google Workspace account state changed during permission review. Retry safely."
            )
        if _has_unresolved_install_receipts():
            raise GoogleWorkspacePlatformSyncPending(
                "Google connection metadata acknowledgement is still pending."
            )
        _wipe_invalid_credentials_and_pending_handoffs_locked()
        requested_profile, client, platform_auth = _resolve_profile_for_connection_locked(
            current_target,
            account_id=account_id,
            exact_permissions=exact_permissions,
            client=client,
            platform_auth=platform_auth,
        )
        if requested_profile.legacy_profile or requested_profile.blocked_scopes:
            raise GoogleWorkspaceScopeReviewRequired(requested_profile)
        if not _same_scope_request(current_target, requested_profile):
            raise GoogleWorkspaceError(
                "Google Workspace account state changed during permission review. Retry safely."
            )
        requested_profile = _profile_with_authoritative_policy(
            requested_profile,
            manifest_version=authoritative_manifest_version,
            client_policy_id=authoritative_client_policy_id,
        )
        if client is None or platform_auth is None:  # pragma: no cover - defensive typing
            raise GoogleWorkspaceError("Google Workspace platform authentication is unavailable.")
        # Adding a second account must first move any legacy singleton into the
        # owner-only multi-account store. Failure leaves the legacy file intact.
        _migrate_legacy_credentials_locked(
            client=client,
            platform_auth=platform_auth,
        )
        private_key_pem, public_key_pem = _generate_key_pair()
        generation = secrets.token_urlsafe(32)
        connection_action = "replace" if account_id is not None else "add"
        button_label = _google_authorization_button_label(
            requested_profile,
            permission_change=account_id is not None,
        )
        start_payload: dict[str, Any] = {
            "public_key_pem": public_key_pem,
            "key_algorithm": KEY_ALGORITHM,
            "capability_bundle": requested_profile.capability_bundle,
            "requested_services": list(requested_profile.services),
            "requested_scopes": list(requested_profile.scopes),
            "connection_action": connection_action,
        }
        if account_id is not None:
            start_payload["connection_id"] = account_id
        try:
            handoff = client.post_json(
                computer_api_path(platform_auth, GOOGLE_WORKSPACE_API_SUFFIX),
                start_payload,
            )
        except PlatformError as exc:
            blocked_profile = _platform_review_required_profile(
                requested_profile,
                exc,
            )
            if blocked_profile is not None:
                raise GoogleWorkspaceScopeReviewRequired(blocked_profile) from exc
            malformed_review = _malformed_platform_review_error(exc)
            if malformed_review is not None:
                raise malformed_review from exc
            raise
        handoff_id = _validated_handoff_id(handoff.get("handoff_id"))
        returned_connection_id = _validated_connection_id(handoff.get("connection_id"))
        if account_id is not None and not hmac.compare_digest(
            returned_connection_id,
            account_id,
        ):
            raise GoogleWorkspaceError("Platform returned another Google connection.")
        capability_bundle = _validated_capability_bundle(
            handoff.get("capability_bundle"),
            expected=requested_profile.capability_bundle,
        )
        services = _normalize_profile_services(
            requested_profile,
            handoff.get("services"),
        )
        scopes = _normalize_workspace_scopes(
            handoff.get("scopes"),
            expected=requested_profile.scopes,
        )
        poll_after_ms = _poll_after_ms(handoff.get("poll_after_ms"))
        authorization_url = _validated_authorization_url(
            handoff.get("authorization_url"),
            platform_base_url=getattr(client, "base_url", None),
        )
        # The platform accepted the policy-gated request. Only now supersede an
        # unconfirmed local disconnect ceremony; a 403 review response leaves
        # every local lifecycle marker untouched.
        ACTIVE_DISCONNECT_PATH.unlink(missing_ok=True)
        try:
            _start_worker_process(
                handoff=handoff,
                private_key_pem=private_key_pem,
                generation=generation,
                handoff_metadata={
                    "capability_bundle": capability_bundle,
                    "services": services,
                    "scopes": scopes,
                    "connection_action": connection_action,
                    "target_connection_id": returned_connection_id,
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
                    expected_connection_id=returned_connection_id,
                )
            raise
        button_result = _send_google_connect_button(
            authorization_url,
            profile=requested_profile,
            permission_change=account_id is not None,
        )
        if not button_result.get("ok"):
            with contextlib.suppress(Exception):
                _claim_handoff(
                    client=client,
                    platform_auth=platform_auth,
                    handoff_id=handoff_id,
                    installed=False,
                    message="Connect Google button could not be delivered.",
                    expected_connection_id=returned_connection_id,
                )
            raise GoogleWorkspaceError("Could not deliver the Connect Google button.")
    private_key_pem = ""
    generation = ""
    return {
        "schema": "tinyhat_google_workspace_action_v1",
        "action": "set_permissions" if exact_permissions else "connect",
        "account_id": returned_connection_id,
        "connection_action": connection_action,
        "profile": requested_profile.name,
        "presets": list(requested_profile.preset_ids),
        "capability_bundle": requested_profile.capability_bundle,
        "services": list(requested_profile.services),
        "scopes": list(requested_profile.scopes),
        "manifest_version": requested_profile.manifest_version,
        "client_policy_id": requested_profile.client_policy_id,
        **({"reason": requested_profile.reason} if requested_profile.reason is not None else {}),
        "status": "waiting_for_user",
        "button_sent": True,
        "poll_after_ms": poll_after_ms,
        "message": (
            f"I sent a native {button_label} button in Telegram. Use that button "
            f"to review {requested_profile.access_label} on Google's consent screen. "
            "Google shows the permissions being requested, and you decide whether "
            "to grant them or return and ask for narrower access. "
            "No plain authorization link is returned. Existing accounts and the "
            "selected account's current credential stay usable unless this encrypted "
            "handoff completes successfully."
        ),
        "handoff_started": bool(handoff_id),
    }


def _validated_handoff_id(value: Any) -> str:
    handoff_id = str(value or "").strip()
    if HANDOFF_ID_RE.fullmatch(handoff_id) is None:
        raise GoogleWorkspaceError("Platform returned an invalid handoff id.")
    return handoff_id


def _validated_authorization_url(
    value: Any,
    *,
    platform_base_url: str | None = None,
) -> str:
    authorization_url = str(value or "").strip()
    parsed = parse.urlsplit(authorization_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise GoogleWorkspaceError(
            "Platform returned an invalid Google authorization URL."
        ) from exc
    direct_google_url = (
        parsed.scheme == "https"
        and parsed.hostname == GOOGLE_AUTHORIZATION_HOST
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and parsed.path == GOOGLE_AUTHORIZATION_PATH
        and bool(parsed.query)
        and not parsed.fragment
    )
    if direct_google_url and len(authorization_url) <= AUTHORIZATION_URL_MAX_LENGTH:
        # Rolling compatibility while platform deployments move from direct
        # Google buttons to the Tinyhat preparation page.
        return authorization_url

    platform_url = parse.urlsplit(str(platform_base_url or "").strip())
    try:
        platform_port = platform_url.port
    except ValueError as exc:
        raise GoogleWorkspaceError(
            "Platform returned an invalid Google authorization URL."
        ) from exc
    trusted_prepare_url = (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and parsed.path == TINYHAT_GOOGLE_PREPARE_PATH
        and not parsed.query
        and GOOGLE_LAUNCH_TICKET_RE.fullmatch(parsed.fragment) is not None
        and len(parsed.fragment) <= GOOGLE_LAUNCH_TICKET_MAX_LENGTH
        and platform_url.scheme == "https"
        and platform_url.hostname is not None
        and platform_url.username is None
        and platform_url.password is None
        and platform_port in {None, 443}
        and parsed.hostname == platform_url.hostname
        and (port or 443) == (platform_port or 443)
        and len(authorization_url) <= AUTHORIZATION_URL_MAX_LENGTH
    )
    if not trusted_prepare_url:
        raise GoogleWorkspaceError("Platform returned an invalid Google authorization URL.")
    return authorization_url


def _send_google_connect_button(
    authorization_url: str,
    *,
    profile: GoogleWorkspaceProfile | str | None = None,
    permission_change: bool = False,
) -> dict[str, bool]:
    """Send the platform URL only inside a native Telegram button."""
    requested_profile = (
        profile if isinstance(profile, GoogleWorkspaceProfile) else _requested_profile(profile)
    )
    button_label = _google_authorization_button_label(
        requested_profile,
        permission_change=permission_change,
    )
    action_label = (
        "Change Google Workspace permissions" if permission_change else "Connect Google Workspace"
    )
    try:
        # Lazy import avoids the tools -> google_workspace registration cycle.
        from .tools import _telegram_credentials, _telegram_send_message  # noqa: PLC0415

        token, chat_id = _telegram_credentials()
        sent = _telegram_send_message(
            token=token,
            chat_id=chat_id,
            text=(f"{action_label} with {requested_profile.access_label}."),
            reply_markup={"inline_keyboard": [[{"text": button_label, "url": authorization_url}]]},
        )
        ok = bool(sent.get("ok"))
        return {"sent": ok, "ok": ok}
    except Exception:
        return {"sent": False, "ok": False}


def _google_authorization_button_label(
    profile: GoogleWorkspaceProfile,
    *,
    permission_change: bool = False,
) -> str:
    """Distinguish first connection from a permission expansion in Telegram."""
    if permission_change:
        return "Change Google access"
    return "Connect Google"


def _validated_capability_bundle(value: Any, *, expected: str | None = None) -> str:
    allowed = {
        GOOGLE_CUSTOM_CAPABILITY_BUNDLE,
        *(profile.capability_bundle for profile in GOOGLE_PROFILE_CONFIGS.values()),
    }
    if not isinstance(value, str) or value not in allowed:
        raise GoogleWorkspaceError("Platform returned an unexpected capability bundle.")
    if expected is not None and value != expected:
        raise GoogleWorkspaceError("Platform returned an unexpected capability bundle.")
    return value


def _normalize_workspace_services(
    value: Any,
    *,
    expected: tuple[str, ...] = GOOGLE_REQUESTED_SERVICES,
) -> list[str]:
    if value != list(expected):
        raise GoogleWorkspaceError("Platform returned unexpected Google services.")
    return list(expected)


def _normalize_profile_services(
    profile: GoogleWorkspaceProfile,
    value: Any,
) -> list[str]:
    """Derive custom display metadata while keeping fixed bundles exact."""
    if profile.capability_bundle == GOOGLE_CUSTOM_CAPABILITY_BUNDLE:
        return list(profile.services)
    return _normalize_workspace_services(value, expected=profile.services)


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


def _start_disconnect_intent(*, account_id: str | None = None) -> dict[str, Any]:
    """Start the platform-owned two-stage Telegram disconnect ceremony."""
    if _owner_entry_exists(LEGACY_CREDENTIALS_PATH):
        _migrate_legacy_credentials()
    credentials, verification = _verified_credentials(account_id)
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

    connection_id = _validated_connection_id(credentials.get("tinyhat_connection_id"))
    telegram_user_id = _trusted_telegram_user_id()
    client, platform_auth = build_platform_client()
    created = client.post_json(
        computer_api_path(
            platform_auth,
            GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX,
        ),
        {
            "telegram_user_id": telegram_user_id,
            "connection_id": connection_id,
        },
    )
    intent = _normalize_disconnect_intent_create(
        created,
        client=client,
        platform_auth=platform_auth,
        connection_id=connection_id,
        account_email=str(credentials["email"]),
    )
    state_path: Path | None = None
    worker_started = False
    try:
        with _lifecycle_lock():
            current = _read_credentials(connection_id)
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
                connection_id=connection_id,
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
            expected_connection_id=intent.connection_id,
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
        "account_id": connection_id,
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
    connection_id: str,
    account_email: str,
) -> GoogleWorkspaceDisconnectIntent:
    if not isinstance(value, dict):
        raise GoogleWorkspaceError("Platform returned an invalid disconnect intent.")
    if value.get("schema") != GOOGLE_WORKSPACE_DISCONNECT_INTENT_SCHEMA:
        raise GoogleWorkspaceError("Platform returned an invalid disconnect schema.")
    if value.get("status") != "created":
        raise GoogleWorkspaceError("Platform did not create the disconnect intent.")
    expected_connection_id = _validated_connection_id(connection_id)
    returned_connection_id = _validated_connection_id(value.get("connection_id"))
    if not hmac.compare_digest(returned_connection_id, expected_connection_id):
        raise GoogleWorkspaceError("Platform returned another Google connection.")
    returned_email = value.get("account_email")
    if (
        not isinstance(returned_email, str)
        or not returned_email.strip()
        or not hmac.compare_digest(
            returned_email.strip().casefold().encode("utf-8"),
            account_email.casefold().encode("utf-8"),
        )
    ):
        raise GoogleWorkspaceError("Platform returned another Google account.")
    intent_id = _validated_handoff_id(value.get("intent_id"))
    owner_token = _validated_disconnect_owner_token(value.get("owner_token"))
    expires_at = _validated_disconnect_expires_at(value.get("expires_at"))
    return GoogleWorkspaceDisconnectIntent(
        client=client,
        platform_auth=platform_auth,
        intent_id=intent_id,
        owner_token=owner_token,
        connection_id=expected_connection_id,
        credential_generation="",
        expires_at=expires_at,
        poll_after_ms=_poll_after_ms(value.get("poll_after_ms")),
    )


def _normalize_disconnect_intent_response(
    value: Any,
    *,
    expected_intent_id: str,
    expected_connection_id: str,
) -> str:
    if not isinstance(value, dict):
        raise GoogleWorkspaceError("Platform returned invalid disconnect state.")
    schema = value.get("schema")
    if schema is not None and schema != GOOGLE_WORKSPACE_DISCONNECT_INTENT_SCHEMA:
        raise GoogleWorkspaceError("Platform returned an invalid disconnect schema.")
    returned_id = value.get("intent_id")
    if returned_id is not None and not hmac.compare_digest(
        _validated_handoff_id(returned_id),
        expected_intent_id,
    ):
        raise GoogleWorkspaceError("Platform returned another disconnect intent.")
    returned_connection_id = _validated_connection_id(value.get("connection_id"))
    if not hmac.compare_digest(
        returned_connection_id,
        _validated_connection_id(expected_connection_id),
    ):
        raise GoogleWorkspaceError("Platform returned another Google connection.")
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
            "tinyhat_connection_id",
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
                    "connection_id": intent.connection_id,
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


def _validated_disconnect_worker_state(*, intent_id: str, state_path: Path) -> dict[str, Any]:
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
        "connection_id",
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
        "connection_id": _validated_connection_id(value.get("connection_id")),
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
        connection_id=value["connection_id"],
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
        if _read_credentials(intent.connection_id) is not None:
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
                expected_connection_id=intent.connection_id,
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
        expected_connection_id=intent.connection_id,
    )
    if status == "confirmed" and response.get("deletion_claimed") is True:
        return "confirmed"
    if status in DISCONNECT_INTENT_TERMINAL_STATUSES:
        return status
    return "deletion_claim_rejected"


def _current_disconnect_credential_status(
    intent: GoogleWorkspaceDisconnectIntent,
) -> tuple[dict[str, Any] | None, str]:
    current = _read_credentials(intent.connection_id)
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
                        _delete_credentials_locked(account_id=intent.connection_id)
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
        expected_connection_id=intent.connection_id,
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


def _poll_and_install(  # noqa: PLR0911, PLR0912, PLR0915
    handoff: GoogleWorkspaceWorkerHandoff,
) -> None:
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
            if (
                terminal_state == "failed"
                and state.get("error_code") == "account_already_connected"
            ):
                # This is the one reviewed platform error safe to surface as a
                # duplicate. Arbitrary platform error text remains generic.
                terminal_state = "duplicate_account"
            elif terminal_state == "failed" and state.get("error_code") == "invalid_scope":
                # Google may grant fewer, extra, or historically merged scopes.
                # Keep exact-grant validation and give the user a useful,
                # narrower-permission recovery path instead of an identical retry.
                terminal_state = "scope_mismatch"
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
                        expected_connection_id=handoff.target_connection_id,
                    )
                    return
                if outcome in {"duplicate_account", "invalid_replacement"}:
                    notification_attempted = True
                    _clear_active_handoff(handoff)
                    notice = "duplicate_account" if outcome == "duplicate_account" else "failed"
                    _send_google_workspace_notice(notice)
                    _claim_handoff(
                        client=handoff.client,
                        platform_auth=handoff.platform_auth,
                        handoff_id=handoff.handoff_id,
                        installed=False,
                        message=(
                            "That Google account is already connected on this Computer."
                            if outcome == "duplicate_account"
                            else "Google account identity changed during the permission update."
                        ),
                        expected_connection_id=handoff.target_connection_id,
                    )
                    return
                installed = True
                _processed, ready_notice = _acknowledge_install_receipt(
                    path=_install_receipt_path(handoff.handoff_id),
                    client=handoff.client,
                    platform_auth=handoff.platform_auth,
                )
                if ready_notice is not None:
                    notification_attempted = True
                    _send_google_workspace_notice(ready_notice)
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
        if not installed:
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
                    installed=False,
                    message=TERMINAL_HANDOFF_MESSAGES["failed"],
                    expected_connection_id=handoff.target_connection_id,
                )
            if not notification_attempted:
                _send_google_workspace_notice("failed")
        raise


TERMINAL_HANDOFF_MESSAGES = {
    "cancelled": "Google sign-in was cancelled. Start connect again when you are ready.",
    "failed": "Google sign-in failed. Start a new connection and try again.",
    "expired": "Google sign-in expired. Start connect again for a fresh link.",
    "superseded": "This Google sign-in was replaced by a newer connection attempt.",
    "duplicate_account": "That Google account is already connected on this Computer.",
    "scope_mismatch": (
        "Google returned different permissions than requested. Tinyhat saved no new "
        "Computer credential. Retry only after the user chooses the exact narrower access."
    ),
}

TELEGRAM_NOTICE_MESSAGES = {
    "ready": ("Google is connected on this Computer with the previously granted access."),
    "ready_identity_only": (
        "Google is connected on this Computer for account identity only. No Gmail, "
        "Calendar, or Drive data access was requested."
    ),
    "ready_workspace_reader": (
        "Google Workspace is connected on this Computer with read-only access to "
        "Gmail messages, threads, and settings, Calendar events, and Drive files."
    ),
    "ready_mail_writer": (
        "Google Workspace Mail Writer access is connected on this Computer for "
        "drafts and confirmed email sending. It does not manage the inbox."
    ),
    "ready_inbox_manager": (
        "Google Workspace Inbox Manager access is connected on this Computer for "
        "mail, drafts, labels, archive, and read state without immediate permanent "
        "deletion. I will still ask before each write."
    ),
    "ready_calendar_coordinator": (
        "Google Workspace Calendar Coordinator access is connected on this Computer. "
        "I will still ask before creating, changing, or deleting an event."
    ),
    "ready_file_collaborator": (
        "Google Workspace File Collaborator access is connected on this Computer for "
        "files Tinyhat creates or files you explicitly share with the app, without "
        "access to other Drive files. "
        "I will still ask before each write."
    ),
    "ready_gmail_send": (
        "Google Workspace permissions were updated on this Computer. Read-only "
        "Gmail, Calendar, and Drive access remains available, and Gmail sending "
        "is now enabled. I will still ask before sending an email."
    ),
    "ready_calendar_write": (
        "Google Workspace permissions were updated on this Computer. Read-only "
        "Gmail, Calendar, and Drive access remains available, and Calendar event "
        "changes are now enabled. I will still ask before changing an event."
    ),
    "ready_gmail_send_calendar_write": (
        "Google Workspace permissions were updated on this Computer. Read-only "
        "Gmail, Calendar, and Drive access remains available, Gmail sending and "
        "Calendar event changes are now enabled, and I will still ask before each write."
    ),
    "ready_workspace_readonly": (
        "Google Workspace is connected on this Computer with the historical read-only "
        "Gmail, Calendar, and Drive grant."
    ),
    "ready_workspace_recommended": (
        "Google Workspace is connected on this Computer with Gmail reading, composing, "
        "sending, and inbox/draft/label management while messages and threads cannot "
        "bypass Trash for immediate permanent deletion, Calendar event management, and "
        "read-only Drive access. I will still ask before "
        "external write actions such as sending email."
    ),
    "ready_workspace_custom": (
        "Google Workspace permissions were updated on this Computer with the exact "
        "access approved on Google's consent screen. I will still ask before external "
        "write actions."
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
    "duplicate_account": (
        "That Google account is already connected on this Computer. Use its existing "
        "account when changing permissions."
    ),
    "scope_mismatch": (
        "Google returned different permissions than requested, so Tinyhat saved no new "
        "credential on this Computer. Tell me the exact narrower Google access you want, "
        "and I can make a new permission request."
    ),
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


def _install_receipt_path(handoff_id: str) -> Path:
    return INSTALL_RECEIPTS_DIR / f"{_validated_handoff_id(handoff_id)}.json"


def _has_unresolved_install_receipts() -> bool:
    try:
        directory_stat = os.lstat(INSTALL_RECEIPTS_DIR)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_uid != os.getuid():
        return True
    try:
        return any(INSTALL_RECEIPTS_DIR.glob("gwo_*.json"))
    except OSError:
        return True


def _sweep_install_receipt_temps() -> None:
    try:
        directory_stat = os.lstat(INSTALL_RECEIPTS_DIR)
    except OSError:
        return
    if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_uid != os.getuid():
        return
    try:
        candidates = sorted(INSTALL_RECEIPTS_DIR.glob(".install-receipt-*"))[
            :INSTALL_RECEIPT_SCAN_LIMIT
        ]
    except OSError:
        return
    for path in candidates:
        try:
            path_stat = os.lstat(path)
            if stat.S_ISREG(path_stat.st_mode) and path_stat.st_uid == os.getuid():
                path.unlink(missing_ok=True)
        except OSError:
            continue


def _delete_all_install_receipts_locked() -> None:
    try:
        directory_stat = os.lstat(INSTALL_RECEIPTS_DIR)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_uid != os.getuid():
        raise GoogleWorkspaceError("Google install receipt directory is unsafe.")
    for path in list(INSTALL_RECEIPTS_DIR.iterdir()):
        path_stat = os.lstat(path)
        if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_uid != os.getuid():
            raise GoogleWorkspaceError("Google install receipt is unsafe.")
        path.unlink(missing_ok=True)
    INSTALL_RECEIPTS_DIR.rmdir()


def _write_install_receipt(
    *,
    handoff: GoogleWorkspaceWorkerHandoff,
    credentials: dict[str, Any],
    phase: str,
) -> Path:
    if phase not in {"install_pending", "claim_pending"}:
        raise GoogleWorkspaceError("Google install receipt phase is invalid.")
    profile = _profile_for_capability_bundle(
        credentials.get("capability_bundle"),
        scopes=credentials.get("scopes"),
        services=credentials.get("services"),
    )
    notice_state = f"ready_{profile.name}"
    path = _install_receipt_path(handoff.handoff_id)
    _atomic_write_json(
        path=path,
        value={
            "schema": GOOGLE_WORKSPACE_INSTALL_RECEIPT_SCHEMA,
            "handoff_id": handoff.handoff_id,
            "owner_token": handoff.owner_token,
            "connection_id": _validated_connection_id(credentials.get("tinyhat_connection_id")),
            "credential_generation": _install_credential_generation(credentials),
            "phase": phase,
            "notice_state": notice_state,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        temporary_prefix=".install-receipt-",
    )
    return path


def _read_install_receipt(path: Path) -> dict[str, str]:
    if path.parent != INSTALL_RECEIPTS_DIR or path.suffix != ".json":
        raise GoogleWorkspaceError("Google install receipt path is invalid.")
    handoff_id = _validated_handoff_id(path.stem)
    value = _read_owner_only_json(path, label="Google install receipt")
    expected_fields = {
        "schema",
        "handoff_id",
        "owner_token",
        "connection_id",
        "credential_generation",
        "phase",
        "notice_state",
        "created_at",
    }
    if set(value) != expected_fields:
        raise GoogleWorkspaceError("Google install receipt is invalid.")
    if value.get("schema") != GOOGLE_WORKSPACE_INSTALL_RECEIPT_SCHEMA:
        raise GoogleWorkspaceError("Google install receipt schema is invalid.")
    if not hmac.compare_digest(_validated_handoff_id(value.get("handoff_id")), handoff_id):
        raise GoogleWorkspaceError("Google install receipt handoff changed.")
    owner_token = str(value.get("owner_token") or "")
    if DISCONNECT_GENERATION_RE.fullmatch(owner_token) is None:
        raise GoogleWorkspaceError("Google install receipt owner is invalid.")
    generation = str(value.get("credential_generation") or "")
    if DISCONNECT_GENERATION_RE.fullmatch(generation) is None:
        raise GoogleWorkspaceError("Google install receipt generation is invalid.")
    phase = str(value.get("phase") or "")
    if phase not in {"install_pending", "claim_pending"}:
        raise GoogleWorkspaceError("Google install receipt phase is invalid.")
    notice_state = str(value.get("notice_state") or "")
    if notice_state not in {
        "ready",
        "ready_gmail_send",
        "ready_calendar_write",
        "ready_gmail_send_calendar_write",
        "ready_workspace_recommended",
        "ready_workspace_custom",
        "ready_workspace_readonly",
        "ready_identity_only",
        "ready_workspace_reader",
        "ready_mail_writer",
        "ready_inbox_manager",
        "ready_calendar_coordinator",
        "ready_file_collaborator",
    }:
        raise GoogleWorkspaceError("Google install receipt notice is invalid.")
    created_at = str(value.get("created_at") or "")
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoogleWorkspaceError("Google install receipt time is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GoogleWorkspaceError("Google install receipt time is invalid.")
    return {
        "handoff_id": handoff_id,
        "owner_token": owner_token,
        "connection_id": _validated_connection_id(value.get("connection_id")),
        "credential_generation": generation,
        "phase": phase,
        "notice_state": notice_state,
    }


def _delete_install_receipt(path: Path) -> None:
    if path.parent != INSTALL_RECEIPTS_DIR or path.suffix != ".json":
        raise GoogleWorkspaceError("Google install receipt path is invalid.")
    path.unlink(missing_ok=True)


def _resume_retained_install_receipts() -> int:
    try:
        directory_stat = os.lstat(INSTALL_RECEIPTS_DIR)
    except OSError:
        return 0
    if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_uid != os.getuid():
        return 0
    with _lifecycle_lock():
        _sweep_install_receipt_temps()
    try:
        paths = sorted(INSTALL_RECEIPTS_DIR.glob("gwo_*.json"))[:INSTALL_RECEIPT_SCAN_LIMIT]
    except OSError:
        return 0
    if not paths:
        return 0
    client, platform_auth = build_platform_client()
    completed = 0
    for path in paths:
        try:
            processed, notice_state = _acknowledge_install_receipt(
                path=path,
                client=client,
                platform_auth=platform_auth,
            )
            if processed:
                completed += 1
            if notice_state is not None:
                _send_google_workspace_notice(notice_state)
        except Exception:
            continue
    return completed


def _acknowledge_install_receipt(
    *,
    path: Path,
    client: PlatformClient,
    platform_auth: str,
) -> tuple[bool, str | None]:
    """Let exactly one worker claim and retire one durable install receipt."""
    with _lifecycle_lock():
        if not path.exists():
            return False, None
        receipt = _read_install_receipt(path)
        current = _read_credentials(receipt["connection_id"])
        generation_matches = bool(
            current is not None
            and hmac.compare_digest(
                _install_credential_generation(current),
                receipt["credential_generation"],
            )
        )
        assignment_matches = bool(
            generation_matches
            and current is not None
            and _assignment_binding_matches_platform(
                credentials=current,
                client=client,
                platform_auth=platform_auth,
            )
        )
        if generation_matches and not assignment_matches:
            ACTIVE_DISCONNECT_PATH.unlink(missing_ok=True)
            _cancel_all_pending_handoffs_locked()
            _delete_credentials_locked()
            _delete_all_install_receipts_locked()
        if not (generation_matches and assignment_matches):
            try:
                _claim_handoff(
                    client=client,
                    platform_auth=platform_auth,
                    handoff_id=receipt["handoff_id"],
                    installed=False,
                    message="Google credential installation did not complete.",
                    expected_connection_id=receipt["connection_id"],
                )
            except Exception:
                pass
            finally:
                # With no matching local generation there is nothing left to
                # reconcile as installed. Old-assignment negative claims can
                # be rejected, so the receipt must not persist forever.
                _delete_install_receipt(path)
            return True, None
        _claim_handoff_with_retry(
            client=client,
            platform_auth=platform_auth,
            handoff_id=receipt["handoff_id"],
            expected_connection_id=receipt["connection_id"],
        )
        _delete_install_receipt(path)
        _remove_active_handoff_marker_if_matches(
            handoff_id=receipt["handoff_id"],
            owner_token=receipt["owner_token"],
        )
        return True, receipt["notice_state"]


def _finish_terminal_handoff(*, handoff: GoogleWorkspaceWorkerHandoff, terminal_state: str) -> None:
    _clear_active_handoff(handoff)
    _send_google_workspace_notice(terminal_state)
    _claim_handoff(
        client=handoff.client,
        platform_auth=handoff.platform_auth,
        handoff_id=handoff.handoff_id,
        installed=False,
        message=TERMINAL_HANDOFF_MESSAGES[terminal_state],
        expected_connection_id=handoff.target_connection_id,
    )


def _install_ready_credentials(  # noqa: PLR0911, PLR0912
    *, handoff: GoogleWorkspaceWorkerHandoff, state: dict[str, Any]
) -> str:
    credentials = _decrypt_ready_credentials(handoff.private_key_pem, state)
    if credentials["capability_bundle"] != handoff.expected_capability_bundle:
        raise GoogleWorkspaceError("Google capability bundle changed during handoff.")
    if credentials["services"] != handoff.expected_services:
        raise GoogleWorkspaceError("Google services changed during handoff.")
    if credentials["scopes"] != handoff.expected_scopes:
        raise GoogleWorkspaceError("Google scopes changed during handoff.")
    connection_id = _validated_connection_id(credentials.get("tinyhat_connection_id"))
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
        accounts = _read_account_store()
        if handoff.connection_action == "replace":
            target_connection_id = _validated_connection_id(handoff.target_connection_id)
            if not hmac.compare_digest(connection_id, target_connection_id):
                return "invalid_replacement"
            current = next(
                (
                    item
                    for item in accounts
                    if hmac.compare_digest(
                        str(item["tinyhat_connection_id"]),
                        target_connection_id,
                    )
                ),
                None,
            )
            if current is None or not hmac.compare_digest(
                str(current["google_subject"]),
                str(credentials["google_subject"]),
            ):
                return "invalid_replacement"
        elif handoff.connection_action == "add":
            target_connection_id = _validated_connection_id(handoff.target_connection_id)
            if not hmac.compare_digest(connection_id, target_connection_id):
                return "invalid_replacement"
            if any(
                hmac.compare_digest(
                    str(item["google_subject"]),
                    str(credentials["google_subject"]),
                )
                or hmac.compare_digest(
                    str(item["tinyhat_connection_id"]),
                    connection_id,
                )
                for item in accounts
            ):
                return "duplicate_account"
        else:
            return "invalid_replacement"
        receipt_path = _write_install_receipt(
            handoff=handoff,
            credentials=credentials,
            phase="install_pending",
        )
        saved = False
        try:
            _atomic_save_credentials(credentials)
            saved = True
            _write_install_receipt(
                handoff=handoff,
                credentials=credentials,
                phase="claim_pending",
            )
        except Exception:
            if not saved:
                _delete_install_receipt(receipt_path)
            raise
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
    scopes = _normalize_workspace_scopes(value.get("scopes"))
    profile = _profile_for_capability_bundle(
        value.get("capability_bundle"),
        scopes=scopes,
        services=value.get("services"),
    )
    # Custom scopes are authoritative. Persist the current plugin's derived
    # service projection so mapping changes cannot strand old Computers.
    normalized_services = _normalize_profile_services(profile, value.get("services"))
    normalized: dict[str, Any] = {
        "schema": GOOGLE_WORKSPACE_CREDENTIAL_SCHEMA,
        "capability_bundle": profile.capability_bundle,
        "services": normalized_services,
        "token_uri": _validated_token_uri(value.get("token_uri")),
        "tinyhat_connection_id": _validated_connection_id(value.get("tinyhat_connection_id")),
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
    return list(_canonical_custom_grant_scopes(scopes))


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


def _validated_connection_id(value: Any, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    connection_id = str(value or "").strip()
    if GOOGLE_CONNECTION_ID_RE.fullmatch(connection_id) is None:
        raise GoogleWorkspaceError("Google connection id was invalid.")
    return connection_id


def _account_store_document(accounts: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = sorted(
        (_normalize_saved_credentials(dict(item), require_connection_id=True) for item in accounts),
        key=lambda item: str(item["tinyhat_connection_id"]),
    )
    connection_ids = [str(item["tinyhat_connection_id"]) for item in normalized]
    if len(connection_ids) != len(set(connection_ids)):
        raise GoogleWorkspaceError("Saved Google account ids are not unique.")
    subjects = [str(item["google_subject"]) for item in normalized]
    if len(subjects) != len(set(subjects)):
        raise GoogleWorkspaceError("The same Google account cannot be connected twice.")
    return {
        "schema": GOOGLE_WORKSPACE_ACCOUNTS_SCHEMA,
        "accounts": normalized,
    }


def _atomic_save_account_store(accounts: list[dict[str, Any]]) -> None:
    _refuse_unsafe_credentials_entry(path=CREDENTIALS_PATH)
    _atomic_write_json(
        path=CREDENTIALS_PATH,
        value=_account_store_document(accounts),
        temporary_prefix=".accounts-",
    )


def _atomic_save_credentials(credentials: dict[str, Any]) -> None:
    """Upsert one connection while preserving every other local account."""
    normalized = _normalize_saved_credentials(dict(credentials), require_connection_id=True)
    connection_id = str(normalized["tinyhat_connection_id"])
    accounts = _read_account_store()
    replaced = False
    for index, current in enumerate(accounts):
        if hmac.compare_digest(str(current["tinyhat_connection_id"]), connection_id):
            accounts[index] = normalized
            replaced = True
            break
    if not replaced:
        accounts.append(normalized)
    _atomic_save_account_store(accounts)


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise GoogleWorkspaceError("Google Workspace state directory is unsafe.")
    path.chmod(0o700)


def _owner_entry_exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _credentials_entry_exists() -> bool:
    return _owner_entry_exists(CREDENTIALS_PATH) or _owner_entry_exists(LEGACY_CREDENTIALS_PATH)


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


def _refuse_unsafe_credentials_entry(*, path: Path = CREDENTIALS_PATH) -> None:
    if not _owner_entry_exists(path):
        return
    _refuse_unsafe_owner_file(path, label="Saved Google credentials")


def _read_account_store() -> list[dict[str, Any]]:
    if not _owner_entry_exists(CREDENTIALS_PATH):
        return []
    value = _read_owner_only_json(
        CREDENTIALS_PATH,
        label="Saved Google accounts",
    )
    if value.get("schema") != GOOGLE_WORKSPACE_ACCOUNTS_SCHEMA:
        raise GoogleWorkspaceError("Saved Google accounts are invalid.")
    raw_accounts = value.get("accounts")
    if not isinstance(raw_accounts, list):
        raise GoogleWorkspaceError("Saved Google accounts are invalid.")
    return _account_store_document(raw_accounts)["accounts"]


def _read_legacy_credentials() -> dict[str, Any] | None:
    if not _owner_entry_exists(LEGACY_CREDENTIALS_PATH):
        return None
    value = _read_owner_only_json(
        LEGACY_CREDENTIALS_PATH,
        label="Legacy saved Google credentials",
    )
    return _normalize_saved_credentials(value, require_connection_id=False)


def _read_all_credentials() -> list[dict[str, Any]]:
    accounts = _read_account_store()
    legacy = _read_legacy_credentials()
    if legacy is None:
        return accounts
    if accounts:
        if any(
            hmac.compare_digest(
                str(item["google_subject"]),
                str(legacy["google_subject"]),
            )
            for item in accounts
        ):
            return accounts
        return [*accounts, legacy]
    return [legacy]


def _safe_account_metadata(credentials: dict[str, Any]) -> dict[str, Any]:
    profile = _profile_for_capability_bundle(
        credentials["capability_bundle"],
        scopes=credentials.get("scopes"),
        services=credentials.get("services"),
    )
    connection_id = _validated_connection_id(
        credentials.get("tinyhat_connection_id"),
        required=False,
    )
    payload: dict[str, Any] = {
        "account_id": connection_id,
        "email": credentials["email"],
        "email_verified": credentials["email_verified"],
        "profile": profile.name,
        "capability_bundle": profile.capability_bundle,
        "services": list(profile.services),
        "scopes": list(credentials["scopes"]),
        "expires_at": credentials["expires_at"],
        "connected_at": credentials["connected_at"],
        "refresh_supported": True,
    }
    return payload


def _read_credentials(account_id: str | None = None) -> dict[str, Any] | None:
    accounts = _read_all_credentials()
    if not accounts:
        return None
    if account_id is not None:
        clean_account_id = _validated_connection_id(account_id)
        for credentials in accounts:
            current_id = _validated_connection_id(
                credentials.get("tinyhat_connection_id"),
                required=False,
            )
            if current_id is not None and hmac.compare_digest(current_id, clean_account_id):
                return credentials
        return None
    if len(accounts) > 1:
        raise GoogleWorkspaceAccountSelectionRequired(
            [_safe_account_metadata(item) for item in accounts]
        )
    return accounts[0]


def _normalize_saved_credentials(
    value: Any,
    *,
    require_connection_id: bool = True,
) -> dict[str, Any]:
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
        normalized_scopes = _normalize_workspace_scopes(value.get("scopes"))
        profile = _profile_for_capability_bundle(
            value.get("capability_bundle"),
            scopes=normalized_scopes,
            services=value.get("services"),
        )
        value["capability_bundle"] = profile.capability_bundle
        value["services"] = _normalize_profile_services(profile, value.get("services"))
        normalized_scopes = _normalize_workspace_scopes(normalized_scopes, expected=profile.scopes)
    except GoogleWorkspaceError as exc:
        raise GoogleWorkspaceError("Saved Google credential metadata is invalid.") from exc
    if value.get("email_verified") is not True:
        raise GoogleWorkspaceError("Saved Google credential metadata is invalid.")
    value["scopes"] = normalized_scopes
    connection_id = _validated_connection_id(
        value.get("tinyhat_connection_id"),
        required=require_connection_id,
    )
    if connection_id is None:
        value.pop("tinyhat_connection_id", None)
    else:
        value["tinyhat_connection_id"] = connection_id
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


def _fetch_platform_connections(
    *, client: PlatformClient, platform_auth: str
) -> list[dict[str, Any]]:
    response = client.get_json(
        computer_api_path(platform_auth, GOOGLE_WORKSPACE_CONNECTIONS_SUFFIX)
    )
    if response.get("schema") != GOOGLE_WORKSPACE_CONNECTIONS_SCHEMA:
        raise GoogleWorkspaceError("Platform returned invalid Google connections.")
    raw_connections = response.get("connections")
    if not isinstance(raw_connections, list):
        raise GoogleWorkspaceError("Platform returned invalid Google connections.")
    connections: list[dict[str, Any]] = []
    for raw in raw_connections:
        if not isinstance(raw, dict):
            raise GoogleWorkspaceError("Platform returned invalid Google connections.")
        connection_id = _validated_connection_id(raw.get("connection_id"))
        email = raw.get("account_email")
        bundle = raw.get("capability_bundle")
        status = raw.get("connection_status")
        if (
            not isinstance(email, str)
            or not email.strip()
            or not isinstance(bundle, str)
            or status not in {"connected", "disconnected"}
        ):
            raise GoogleWorkspaceError("Platform returned invalid Google connections.")
        connections.append(
            {
                "connection_id": connection_id,
                "account_email": email.strip(),
                "capability_bundle": bundle,
                "connection_status": status,
            }
        )
    return connections


def _fsync_state_directory() -> None:
    directory_fd = os.open(
        STATE_DIR,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _migrate_legacy_credentials_locked(*, client: PlatformClient, platform_auth: str) -> bool:
    """Resolve one legacy singleton to platform metadata before changing custody."""
    legacy = _read_legacy_credentials()
    if legacy is None:
        return False
    matches = [
        item
        for item in _fetch_platform_connections(
            client=client,
            platform_auth=platform_auth,
        )
        if item["connection_status"] == "connected"
        and str(item["account_email"]).casefold() == str(legacy["email"]).casefold()
        and item["capability_bundle"] == legacy["capability_bundle"]
    ]
    if len(matches) != 1:
        raise GoogleWorkspaceError(
            "Legacy Google credentials could not be matched to exactly one connection."
        )
    migrated = dict(legacy)
    migrated["tinyhat_connection_id"] = matches[0]["connection_id"]
    accounts = _read_account_store()
    accounts = [
        current
        for current in accounts
        if str(current["google_subject"]) != str(migrated["google_subject"])
    ]
    accounts.append(migrated)
    _atomic_save_account_store(accounts)
    _refuse_unsafe_owner_file(
        LEGACY_CREDENTIALS_PATH,
        label="Legacy saved Google credentials",
    )
    LEGACY_CREDENTIALS_PATH.unlink()
    _fsync_state_directory()
    return True


def _migrate_legacy_credentials() -> bool:
    if not _owner_entry_exists(LEGACY_CREDENTIALS_PATH):
        return False
    client, platform_auth = build_platform_client()
    with _lifecycle_lock():
        return _migrate_legacy_credentials_locked(
            client=client,
            platform_auth=platform_auth,
        )


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


def _delete_credentials_locked(*, account_id: str | None = None) -> None:
    """Delete one selected account, or every credential on assignment cleanup."""
    if account_id is None:
        # unlink removes a symlink itself without following it. Reads and writes
        # still refuse such entries through lstat and O_NOFOLLOW.
        CREDENTIALS_PATH.unlink(missing_ok=True)
        LEGACY_CREDENTIALS_PATH.unlink(missing_ok=True)
        return
    clean_account_id = _validated_connection_id(account_id)
    accounts = _read_account_store()
    remaining = [
        item
        for item in accounts
        if not hmac.compare_digest(
            str(item["tinyhat_connection_id"]),
            clean_account_id,
        )
    ]
    if len(remaining) == len(accounts):
        raise GoogleWorkspaceError("Google Workspace account is not connected.")
    if remaining:
        _atomic_save_account_store(remaining)
    else:
        CREDENTIALS_PATH.unlink(missing_ok=True)


def _wipe_invalid_credentials_and_pending_handoffs_locked() -> str:
    """Remove malformed owner-readable credentials and every pending handoff."""
    if not _credentials_entry_exists():
        return "not_present"
    try:
        credentials = _read_all_credentials()
    except GoogleWorkspaceError:
        # Only remove owner-readable regular files with no hard links. This may
        # include a mode-drifted file, but never follows a symlink or unlinks a
        # shared inode.
        for path, label in (
            (CREDENTIALS_PATH, "Saved Google accounts"),
            (LEGACY_CREDENTIALS_PATH, "Legacy saved Google credentials"),
        ):
            if _owner_entry_exists(path):
                _refuse_unsafe_owned_readable_file(path, label=label)
        # Delete the credential first so a scratch-cleanup failure cannot leave
        # stale tokens available on the Computer.
        _delete_credentials_locked()
        ACTIVE_DISCONNECT_PATH.unlink(missing_ok=True)
        _cancel_all_pending_handoffs_locked()
        return "invalid"
    return "valid" if credentials else "not_present"


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
        client_kwargs = {} if timeout_seconds is None else {"timeout_seconds": timeout_seconds}
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
    credential_path = (
        CREDENTIALS_PATH if _owner_entry_exists(CREDENTIALS_PATH) else LEGACY_CREDENTIALS_PATH
    )
    try:
        entry = os.lstat(credential_path)
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
        accounts = _read_all_credentials()
    except GoogleWorkspaceError:
        return "invalid", None
    if not accounts:
        return "not_present", None
    bindings = {str(item["tinyhat_assignment_binding"]) for item in accounts}
    if len(bindings) != 1:
        return "invalid", None
    return "present", accounts[0]


def _remove_credentials_for_stale_binding(saved_binding: str) -> str:
    with _lifecycle_lock():
        try:
            current_accounts = _read_all_credentials()
        except GoogleWorkspaceError:
            result = _wipe_invalid_credentials_and_pending_handoffs_locked()
            return "retry" if result == "valid" else result
        if not current_accounts:
            return "not_present"
        if any(
            not hmac.compare_digest(
                saved_binding,
                str(current["tinyhat_assignment_binding"]),
            )
            for current in current_accounts
        ):
            return "retry"
        ACTIVE_DISCONNECT_PATH.unlink(missing_ok=True)
        _cancel_all_pending_handoffs_locked()
        _delete_credentials_locked()
    return "removed"


def _verified_credentials(
    account_id: str | None = None,
) -> tuple[dict[str, Any] | None, str]:
    for _ in range(2):
        verification = remove_credentials_if_assignment_changed()
        if verification == "retry":
            continue
        if verification != "match":
            return None, verification
        try:
            return _read_credentials(account_id), "match"
        except GoogleWorkspaceAccountSelectionRequired:
            raise
        except GoogleWorkspaceError:
            return None, "invalid"
    return None, "unavailable"


def _verified_accounts() -> tuple[list[dict[str, Any]], str]:
    for _ in range(2):
        verification = remove_credentials_if_assignment_changed()
        if verification == "retry":
            continue
        if verification != "match":
            return [], verification
        try:
            return _read_all_credentials(), "match"
        except GoogleWorkspaceError:
            return [], "invalid"
    return [], "unavailable"


def load_verified_google_workspace_credentials(
    account_id: str | None = None,
) -> dict[str, Any]:
    """Load credentials only after current-assignment verification.

    Every Google Workspace operation must use this helper rather than reading
    the local file directly. The connection tool itself does not expose service
    data.
    """
    credentials, verification = _verified_credentials(account_id)
    if verification != "match" or credentials is None:
        raise GoogleWorkspaceError(
            "Google credentials are unavailable for the Computer's current assignment."
        )
    return credentials


def refresh_verified_google_workspace_credentials(
    account_id: str | None = None,
) -> dict[str, Any]:
    """Refresh Google access through the attested platform, never Google directly."""
    credentials = load_verified_google_workspace_credentials(account_id)
    if credentials.get("tinyhat_connection_id") is None:
        _migrate_legacy_credentials()
        credentials = load_verified_google_workspace_credentials(account_id)
    connection_id = _validated_connection_id(credentials.get("tinyhat_connection_id"))
    profile = _profile_for_capability_bundle(
        credentials["capability_bundle"],
        scopes=credentials.get("scopes"),
        services=credentials.get("services"),
    )
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
                "tinyhat_connection_id": connection_id,
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
            expected_connection_id=connection_id,
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
    expected_connection_id: str,
    expected_assignment_binding: str,
    expected_scopes: tuple[str, ...] | list[str] = GOOGLE_RECOMMENDED_SCOPES,
) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema") != GOOGLE_WORKSPACE_REFRESH_SCHEMA:
        raise GoogleWorkspaceError("Refreshed Google access had an invalid schema.")
    allowed_fields = {
        "schema",
        "tinyhat_connection_id",
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
    connection_id = _validated_connection_id(value.get("tinyhat_connection_id"))
    token_type = value.get("token_type")
    expires_at = value.get("expires_at")
    assignment_binding = value.get("tinyhat_assignment_binding")
    if connection_id is None or not hmac.compare_digest(
        connection_id,
        _validated_connection_id(expected_connection_id),
    ):
        raise GoogleWorkspaceError("Google account changed during refresh.")
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
        "tinyhat_connection_id": connection_id,
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
        connection_id = _validated_connection_id(expected.get("tinyhat_connection_id"))
        current = _read_credentials(connection_id)
        if current is None:
            raise GoogleWorkspaceError("Google Workspace was disconnected during refresh.")
        for field in ("client_id", "refresh_token", "tinyhat_assignment_binding"):
            if not hmac.compare_digest(str(current[field]), str(expected[field])):
                raise GoogleWorkspaceError("Google credentials changed during refresh.")
        if not hmac.compare_digest(
            _refresh_credential_generation(current),
            _refresh_credential_generation(expected),
        ):
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


def _refresh_credential_generation(credentials: dict[str, Any]) -> str:
    """Fingerprint every connection field that an access-token refresh cannot change."""
    material = {
        field: credentials.get(field)
        for field in (
            "schema",
            "tinyhat_connection_id",
            "capability_bundle",
            "services",
            "scopes",
            "token_uri",
            "client_id",
            "refresh_token",
            "token_type",
            "google_subject",
            "email",
            "email_verified",
            "connected_at",
            "tinyhat_assignment_binding",
        )
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _install_credential_generation(credentials: dict[str, Any]) -> str:
    """Fingerprint install lineage while allowing normal token refresh rotation."""
    material = {
        field: credentials.get(field)
        for field in (
            "schema",
            "tinyhat_connection_id",
            "capability_bundle",
            "services",
            "scopes",
            "token_uri",
            "client_id",
            "google_subject",
            "email",
            "email_verified",
            "connected_at",
            "tinyhat_assignment_binding",
        )
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _account_store_generation(accounts: list[dict[str, Any]]) -> str:
    """Fingerprint the current installed account set without token rotation."""
    encoded = json.dumps(
        sorted(_install_credential_generation(account) for account in accounts),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _status_payload(*, account_id: str | None = None) -> dict[str, Any]:
    if _owner_entry_exists(LEGACY_CREDENTIALS_PATH):
        try:
            _migrate_legacy_credentials()
        except GoogleWorkspaceError:
            return {
                "schema": "tinyhat_google_workspace_status_v1",
                "action": "status",
                "status": "verification_unavailable",
                "connected": False,
                "message": (
                    "The Computer could not match its existing Google credential to "
                    "current safe connection metadata. Try status again."
                ),
            }
    accounts, verification = _verified_accounts()
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
    if not accounts:
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
    safe_accounts = sorted(
        (_safe_account_metadata(credentials) for credentials in accounts),
        key=lambda item: (str(item["email"]).casefold(), str(item["account_id"])),
    )
    selected: dict[str, Any] | None = None
    if account_id is not None:
        for item in safe_accounts:
            if hmac.compare_digest(str(item["account_id"]), account_id):
                selected = item
                break
        if selected is None:
            raise GoogleWorkspaceError("Google Workspace account is not connected.")
    elif len(safe_accounts) == 1:
        selected = safe_accounts[0]

    result: dict[str, Any] = {
        "schema": "tinyhat_google_workspace_status_v1",
        "action": "status",
        "status": "connected",
        "connected": True,
        "account_count": len(safe_accounts),
        "accounts": safe_accounts,
        "account_selection_required": len(safe_accounts) > 1 and account_id is None,
        "platform_sync_pending": _has_unresolved_install_receipts(),
        "refresh_mode": "tinyhat_platform_broker_v1",
    }
    if selected is not None:
        selected_credentials = next(
            item
            for item in accounts
            if hmac.compare_digest(
                str(item["tinyhat_connection_id"]),
                str(selected["account_id"]),
            )
        )
        result.update(selected)
        result["refresh_token_present"] = bool(selected_credentials.get("refresh_token"))
        result["refresh_available"] = bool(selected_credentials.get("refresh_token"))
    return result


def _claim_handoff(  # noqa: PLR0913
    *,
    client: PlatformClient,
    platform_auth: str,
    handoff_id: str,
    installed: bool,
    message: str | None,
    expected_connection_id: str | None = None,
) -> None:
    response = client.post_json(
        computer_api_path(
            platform_auth,
            f"{GOOGLE_WORKSPACE_API_SUFFIX}/{handoff_id}/claim",
        ),
        {"installed": installed, "message": message},
    )
    if not isinstance(response, dict):
        raise GoogleWorkspaceError("Platform returned an invalid Google claim response.")
    returned_handoff_id = _validated_handoff_id(response.get("handoff_id"))
    if not hmac.compare_digest(returned_handoff_id, _validated_handoff_id(handoff_id)):
        raise GoogleWorkspaceError("Platform claimed another Google handoff.")
    returned_status = str(response.get("status") or "").strip().lower()
    if installed:
        if returned_status != "claimed":
            raise GoogleWorkspaceError("Platform did not acknowledge the Google handoff claim.")
    elif returned_status not in {
        "claimed",
        "cancelled",
        "failed",
        "expired",
        "superseded",
    }:
        raise GoogleWorkspaceError("Platform returned invalid terminal Google handoff state.")
    returned_connection_id = response.get("connection_id")
    if returned_connection_id is not None:
        clean_connection_id = _validated_connection_id(returned_connection_id)
        if expected_connection_id is None or not hmac.compare_digest(
            clean_connection_id,
            _validated_connection_id(expected_connection_id),
        ):
            raise GoogleWorkspaceError("Platform claimed another Google connection.")


def _claim_handoff_with_retry(
    *,
    client: PlatformClient,
    platform_auth: str,
    handoff_id: str,
    expected_connection_id: str,
) -> None:
    """Acknowledge a saved credential before clearing state or notifying."""
    for attempt in range(INSTALL_CLAIM_MAX_ATTEMPTS):
        try:
            _claim_handoff(
                client=client,
                platform_auth=platform_auth,
                handoff_id=handoff_id,
                installed=True,
                message=None,
                expected_connection_id=expected_connection_id,
            )
            return
        except Exception:
            if attempt + 1 >= INSTALL_CLAIM_MAX_ATTEMPTS:
                raise
            time.sleep(INSTALL_CLAIM_RETRY_SECONDS)


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
