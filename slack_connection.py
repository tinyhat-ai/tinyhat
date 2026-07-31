"""Hermes-native Slack connection onboarding and local installation."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any
from urllib import error, parse, request

from .platform import build_platform_client, computer_api_path
from .secret_handoff import (
    HANDOFF_OUTCOME_RESTART_PENDING,
    KEY_ALGORITHM,
    SecretHandoffError,
    _claim_handoff,
    _decrypt_ciphertext,
    _generate_key_pair,
    _send_secret_notice,
    _set_hermes_secret,
    _start_worker_process,
)
from .slack_disconnect import start_slack_disconnect_worker

SLACK_CONNECTION_SECRET_NAME = "SLACK_CONNECTION"
SLACK_CONNECTION_EXPIRES_IN_SECONDS = 30 * 60
MAX_ALLOWED_USERS = 100
SLACK_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{8,}$")
SLACK_API_BASE_URL = "https://slack.com/api"
SLACK_APP_SETTINGS_BASE_URL = "https://api.slack.com/apps"
SLACK_APP_INSTALL_PATH = "install-on-team"
SLACK_HOME_CHANNEL_NAME = "Owner DM"
SLACK_WELCOME_MESSAGE = "Hi there! Slack is connected to this Hermes agent."
SLACK_APP_TOKEN_APP_ID_RE = re.compile(
    r"^xapp-(?:\d+-)?(A[A-Z0-9]{8,})(?:-|$)",
    re.IGNORECASE,
)
REQUIRED_CONNECTION_BOT_SCOPES = (
    "assistant:write",
    "chat:write",
    "im:write",
    "users:read",
)
SAFE_SLACK_ERROR_CODES = {
    "account_inactive",
    "cannot_dm_bot",
    "cannot_dm_user",
    "invalid_app_token",
    "invalid_auth",
    "missing_scope",
    "not_allowed_token_type",
    "not_authed",
    "token_revoked",
    "user_not_found",
    "users_not_found",
}


class SlackConnectionError(SecretHandoffError):
    """A value-blind, stage-aware Slack connection failure."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        code: str,
        public_message: str,
    ) -> None:
        super().__init__(message, public_message=public_message)
        self.stage = stage
        self.code = code


def start_slack_connection(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Send the Hermes manifest and encrypted Slack credential entry flow."""

    del args
    manifest = _generate_hermes_slack_manifest()
    private_key_pem, public_key_pem = _generate_key_pair()
    client, platform_auth = build_platform_client()
    handoff = client.post_json(
        computer_api_path(platform_auth, "private-secret-handoffs/v1"),
        {
            "name": SLACK_CONNECTION_SECRET_NAME,
            "description": "Hermes Slack Socket Mode connection",
            "public_key_pem": public_key_pem,
            "key_algorithm": KEY_ALGORITHM,
            "expires_in_seconds": SLACK_CONNECTION_EXPIRES_IN_SECONDS,
            "handoff_kind": "slack_connection",
            "slack_manifest": manifest,
        },
    )
    if not handoff.get("existing_handoff"):
        _start_worker_process(handoff, private_key_pem)
    return (
        "I sent the Slack app guide, Hermes Agent-view manifest, and secure "
        "Enter Slack details button. Tinyhat never sees the tokens or Slack messages."
    )


def start_slack_disconnect(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Send the owner-confirmed Slack revocation and local removal ceremony."""

    del args
    client, platform_auth = build_platform_client()
    result = client.post_json(
        computer_api_path(platform_auth, "slack/disconnect/v1"),
        {},
    )
    if str(result.get("status") or "") not in {
        "removed",
        "cancelled",
        "expired",
        "failed",
        "superseded",
    }:
        start_slack_disconnect_worker(result)
    result.update(
        {
            "chat_response_required": False,
            "agent_instruction": (
                "The platform sent the expiring two-stage Slack disconnect "
                "confirmation. Do not ask for text confirmation, expose a URL, "
                "or send a duplicate reply."
            ),
        }
    )
    return json.dumps(result, sort_keys=True)


def _generate_hermes_slack_manifest() -> dict[str, Any]:
    hermes = shutil.which("hermes")
    if not hermes:
        raise SecretHandoffError(
            "Hermes CLI was not found.",
            public_message="I could not generate the Hermes Slack manifest.",
        )
    try:
        completed = subprocess.run(
            [hermes, "slack", "manifest", "--agent-view"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SecretHandoffError(
            "Hermes Slack manifest command failed.",
            public_message="I could not generate the Hermes Slack manifest.",
        ) from exc
    if completed.returncode != 0:
        stderr_tail = (completed.stderr or completed.stdout or "").strip()[-500:]
        detail = f": {stderr_tail}" if stderr_tail else ""
        raise SecretHandoffError(
            f"Hermes Slack manifest command returned an error{detail}",
            public_message="I could not generate the Hermes Slack manifest.",
        )
    try:
        manifest = json.loads(completed.stdout)
    except (TypeError, ValueError) as exc:
        raise SecretHandoffError(
            "Hermes Slack manifest output was not JSON.",
            public_message="I could not generate the Hermes Slack manifest.",
        ) from exc
    if not isinstance(manifest, dict):
        raise SecretHandoffError("Hermes Slack manifest output was not an object.")
    _remove_slack_commands(manifest)
    _ensure_connection_scopes(manifest)
    return manifest


def _remove_slack_commands(manifest: dict[str, Any]) -> None:
    """Remove workspace-global slash commands from the per-agent Slack app."""

    features = manifest.get("features")
    if isinstance(features, dict):
        features.pop("slash_commands", None)

    oauth_config = manifest.get("oauth_config")
    if not isinstance(oauth_config, dict):
        return
    scopes = oauth_config.get("scopes")
    if not isinstance(scopes, dict):
        return
    bot_scopes = scopes.get("bot")
    if isinstance(bot_scopes, list):
        scopes["bot"] = [scope for scope in bot_scopes if scope != "commands"]


def _ensure_connection_scopes(manifest: dict[str, Any]) -> None:
    """Make the first installed token sufficient for Tinyhat's Slack checks."""

    oauth_config = manifest.get("oauth_config")
    scopes = oauth_config.get("scopes") if isinstance(oauth_config, dict) else None
    bot_scopes = scopes.get("bot") if isinstance(scopes, dict) else None
    if not isinstance(bot_scopes, list):
        raise SecretHandoffError(
            "Hermes Slack manifest did not include bot scopes.",
            public_message="I could not generate a complete Slack app manifest.",
        )
    normalized = [
        str(scope).strip()
        for scope in bot_scopes
        if isinstance(scope, str) and str(scope).strip()
    ]
    for scope in REQUIRED_CONNECTION_BOT_SCOPES:
        if scope not in normalized:
            normalized.append(scope)
    scopes["bot"] = normalized


def install_submitted_slack_connection(
    *,
    client: Any,
    platform_auth: str,
    handoff_id: str,
    private_key_pem: str,
    state: dict[str, Any],
) -> bool:
    """Install a submitted bundle, preserving the worker for safe retries."""
    ciphertext_payload = state.get("ciphertext_payload")
    if not isinstance(ciphertext_payload, dict):
        raise SecretHandoffError("Platform did not return Slack ciphertext.")
    plaintext = _decrypt_ciphertext(private_key_pem, ciphertext_payload)
    bundle: dict[str, str] = {}
    metadata: dict[str, Any] = {}
    parse_failure: SlackConnectionError | None = None
    try:
        bundle = _parse_connection_bundle(plaintext)
    except Exception as exc:
        parse_failure = _slack_connection_failure(exc)
    finally:
        plaintext = ""
    try:
        if parse_failure is not None:
            raise parse_failure
        metadata = _validate_slack_credentials(bundle)
        home_channel = _open_slack_home_channel(bundle)
        try:
            for name, value in (
                ("SLACK_BOT_TOKEN", bundle["bot_token"]),
                ("SLACK_APP_TOKEN", bundle["app_token"]),
                ("SLACK_ALLOWED_USERS", bundle["allowed_users"]),
                ("SLACK_HOME_CHANNEL", home_channel),
                ("SLACK_HOME_CHANNEL_NAME", SLACK_HOME_CHANNEL_NAME),
            ):
                _set_hermes_secret(name, value)
        except Exception as exc:
            raise SlackConnectionError(
                "Hermes could not save the validated Slack credentials.",
                stage="credential_save",
                code="secret_save_failed",
                public_message=(
                    "Slack accepted the details, but Hermes could not save them "
                    "on this Computer."
                ),
            ) from exc
        _slack_api_call(
            "chat.postMessage",
            token=bundle["bot_token"],
            params={"channel": home_channel, "text": SLACK_WELCOME_MESSAGE},
            stage="greeting",
        )
        _claim_handoff(
            client,
            platform_auth,
            handoff_id,
            installed=True,
            message=None,
            outcome=HANDOFF_OUTCOME_RESTART_PENDING,
            connection_metadata={
                **metadata,
                "connection_status": "connected",
            },
        )
        return True
    except Exception as exc:
        failure = _slack_connection_failure(exc)
        failure_identity = dict(metadata)
        if "app_id" not in failure_identity:
            app_id = _app_id_from_app_token(bundle.get("app_token"))
            if app_id is not None:
                failure_identity["app_id"] = app_id
        failure_metadata = {
            "provider": "slack",
            "connection_status": "failed",
            "failure_stage": failure.stage,
            "failure_code": failure.code,
            "retryable": True,
            **{
                key: failure_identity[key]
                for key in (
                    "app_id",
                    "app_name",
                    "workspace_id",
                    "workspace_name",
                )
                if key in failure_identity
            },
        }
        try:
            _claim_handoff(
                client,
                platform_auth,
                handoff_id,
                installed=False,
                message=failure.public_message,
                connection_metadata=failure_metadata,
            )
        except Exception:
            # Compatibility with platform versions that predate failed
            # connection metadata.
            _send_secret_notice(_slack_failure_notice(failure, failure_identity))
            _claim_handoff(
                client,
                platform_auth,
                handoff_id,
                installed=False,
                message=failure.public_message,
            )
        return False
    finally:
        bundle.clear()


def _slack_connection_failure(exc: Exception) -> SlackConnectionError:
    if isinstance(exc, SlackConnectionError):
        return exc
    if isinstance(exc, SecretHandoffError):
        return SlackConnectionError(
            str(exc),
            stage="input_validation",
            code="invalid_input",
            public_message=exc.public_message,
        )
    return SlackConnectionError(
        "Unexpected Slack connection failure.",
        stage="unknown",
        code="connection_failed",
        public_message="Slack could not be connected. Please retry the setup.",
    )


def _slack_failure_notice(
    failure: SlackConnectionError,
    metadata: dict[str, Any],
) -> str:
    prefix = f"Slack connection failed during {_slack_stage_label(failure.stage)}. "
    app_id = str(metadata.get("app_id") or "").strip().upper()
    if not SLACK_ID_RE.fullmatch(app_id):
        return f"{prefix}{failure.public_message}"
    app_url = f"{SLACK_APP_SETTINGS_BASE_URL}/{app_id}"
    if failure.code == "missing_scope":
        install_url = f"{app_url}/{SLACK_APP_INSTALL_PATH}"
        return (
            "Slack setup · Step 4 of 5. Reinstall the app once to apply the "
            f"manifest permissions, then finish setup: {install_url}"
        )
    return f"{prefix}{failure.public_message} Open the Slack app: {app_url}"


def _slack_stage_label(stage: str) -> str:
    return {
        "bot_auth": "bot-token validation",
        "socket_mode": "Socket Mode validation",
        "member_lookup": "allowed-member validation",
        "app_identity": "Slack app identification",
        "owner_dm": "owner direct-message setup",
        "credential_save": "credential saving",
        "greeting": "welcome-message delivery",
        "input_validation": "submitted-detail validation",
    }.get(stage, "Slack setup")


def _parse_connection_bundle(plaintext: str) -> dict[str, str]:
    try:
        payload = json.loads(plaintext)
    except (TypeError, ValueError) as exc:
        raise SecretHandoffError("Slack connection bundle was not valid JSON.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "tinyhat_slack_connection_bundle_v1"
    ):
        raise SecretHandoffError("Slack connection bundle schema is invalid.")
    bot_token = str(payload.get("bot_token") or "").strip()
    app_token = str(payload.get("app_token") or "").strip()
    allowed_users = _normalize_allowed_users(payload.get("allowed_users"))
    if not bot_token.startswith("xoxb-"):
        raise SecretHandoffError(
            "Slack bot token is invalid.",
            public_message="The Slack bot token must start with xoxb-.",
        )
    if not app_token.startswith("xapp-"):
        raise SecretHandoffError(
            "Slack app token is invalid.",
            public_message="The Slack Socket Mode token must start with xapp-.",
        )
    return {
        "bot_token": bot_token,
        "app_token": app_token,
        "allowed_users": allowed_users,
    }


def _normalize_allowed_users(value: Any) -> str:
    users = [item.strip().upper() for item in str(value or "").split(",") if item.strip()]
    if (
        not users
        or len(users) > MAX_ALLOWED_USERS
        or any(not SLACK_ID_RE.fullmatch(item) for item in users)
    ):
        raise SecretHandoffError(
            "Slack allowed member IDs are invalid.",
            public_message=("Enter the Slack member ID from Profile → More → Copy member ID."),
        )
    return ",".join(dict.fromkeys(users))


def _app_id_from_app_token(value: Any) -> str | None:
    """Read the non-secret app ID embedded in Slack's xapp token shape."""

    match = SLACK_APP_TOKEN_APP_ID_RE.match(str(value or "").strip())
    if match is None:
        return None
    app_id = match.group(1).upper()
    return app_id if SLACK_ID_RE.fullmatch(app_id) else None


def _open_slack_home_channel(bundle: dict[str, str]) -> str:
    """Open the first allowed member's DM and use it as Hermes' home channel."""

    owner_user_id = bundle["allowed_users"].split(",", 1)[0]
    result = _slack_api_call(
        "conversations.open",
        token=bundle["bot_token"],
        params={"users": owner_user_id},
        stage="owner_dm",
    )
    channel = result.get("channel")
    channel_id = (
        str(channel.get("id") or "").strip().upper()
        if isinstance(channel, dict)
        else ""
    )
    if not channel_id.startswith("D") or not SLACK_ID_RE.fullmatch(channel_id):
        raise SlackConnectionError(
            "Slack did not return the owner's direct-message channel.",
            stage="owner_dm",
            code="invalid_response",
            public_message=(
                "Slack accepted the tokens but could not open the owner's "
                "direct message."
            ),
        )
    return channel_id


def _validate_slack_credentials(bundle: dict[str, str]) -> dict[str, Any]:
    auth = _slack_api_call(
        "auth.test",
        token=bundle["bot_token"],
        stage="bot_auth",
    )
    _slack_api_call(
        "apps.connections.open",
        token=bundle["app_token"],
        stage="socket_mode",
    )

    app_id = str(auth.get("app_id") or "").strip().upper()
    if not SLACK_ID_RE.fullmatch(app_id):
        app_id = _app_id_from_app_token(bundle["app_token"]) or ""
    app_name = str(
        auth.get("app_name") or auth.get("user") or "Tinyhat Agent"
    ).strip()[:80]
    bot_id = str(auth.get("bot_id") or "").strip().upper()
    if not SLACK_ID_RE.fullmatch(app_id) and SLACK_ID_RE.fullmatch(bot_id):
        try:
            bot = _slack_api_call(
                "bots.info",
                token=bundle["bot_token"],
                params={"bot": bot_id},
                stage="app_identity",
            ).get("bot")
        except SlackConnectionError:
            bot = None
        if isinstance(bot, dict):
            app_id = str(bot.get("app_id") or "").strip().upper()
            app_name = str(bot.get("name") or app_name).strip()[:80]
    workspace_id = str(auth.get("team_id") or "").strip().upper()
    if not SLACK_ID_RE.fullmatch(workspace_id):
        raise SlackConnectionError(
            "Slack did not return the workspace identifier.",
            stage="app_identity",
            code="identity_missing",
            public_message=(
                "Slack accepted the tokens but did not identify the workspace."
            ),
        )
    metadata = {
        "provider": "slack",
        "app_name": app_name,
        "workspace_id": workspace_id,
        "workspace_name": str(auth.get("team") or workspace_id).strip()[:100],
        "allowed_user_count": len(bundle["allowed_users"].split(",")),
    }
    if SLACK_ID_RE.fullmatch(app_id):
        metadata["app_id"] = app_id
    return metadata


def _slack_api_call(
    method: str,
    *,
    token: str,
    params: dict[str, str] | None = None,
    stage: str = "unknown",
) -> dict[str, Any]:
    body = parse.urlencode(params or {}).encode("utf-8")
    req = request.Request(
        f"{SLACK_API_BASE_URL}/{method}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, ValueError) as exc:
        raise SlackConnectionError(
            f"Slack API validation failed for {method}.",
            stage=stage,
            code="network_error",
            public_message=(
                "Slack could not be reached from this Computer. Please retry."
            ),
        ) from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        error_name = (
            str(payload.get("error") or "unknown_error")
            if isinstance(payload, dict)
            else "invalid_response"
        )
        safe_error_code = (
            error_name if error_name in SAFE_SLACK_ERROR_CODES else "slack_rejected"
        )
        raise SlackConnectionError(
            f"Slack rejected {method}: {error_name[:80]}.",
            stage=stage,
            code=safe_error_code,
            public_message=(
                _slack_failure_message(stage, safe_error_code)
            ),
        )
    return payload


def _slack_failure_message(stage: str, code: str) -> str:
    if code == "missing_scope":
        return (
            "Reinstall the app once to apply the manifest permissions, then "
            "finish setup."
        )
    if stage == "bot_auth":
        return "Slack did not accept the bot token. Copy the xoxb token and retry."
    if stage == "socket_mode":
        return "Slack did not accept the Socket Mode app token. Copy the xapp token and retry."
    if stage == "member_lookup":
        return "Slack could not find an allowed member ID. Copy it from the member profile and retry."
    if stage == "owner_dm":
        return "Slack could not open the owner's direct message."
    if stage == "greeting":
        return "Slack connected, but Hermes could not send the welcome message."
    return "Slack rejected the connection details. Check the Slack app settings and retry."
