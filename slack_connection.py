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

SLACK_CONNECTION_SECRET_NAME = "SLACK_CONNECTION"
SLACK_CONNECTION_EXPIRES_IN_SECONDS = 30 * 60
MAX_ALLOWED_USERS = 100
SLACK_ID_RE = re.compile(r"^[A-Z][A-Z0-9]{8,}$")
SLACK_API_BASE_URL = "https://slack.com/api"


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


def install_submitted_slack_connection(
    *,
    client: Any,
    platform_auth: str,
    handoff_id: str,
    private_key_pem: str,
    state: dict[str, Any],
) -> None:
    ciphertext_payload = state.get("ciphertext_payload")
    if not isinstance(ciphertext_payload, dict):
        raise SecretHandoffError("Platform did not return Slack ciphertext.")
    plaintext = _decrypt_ciphertext(private_key_pem, ciphertext_payload)
    try:
        bundle = _parse_connection_bundle(plaintext)
    finally:
        plaintext = ""

    metadata = _validate_slack_credentials(bundle)
    for name, value in (
        ("SLACK_BOT_TOKEN", bundle["bot_token"]),
        ("SLACK_APP_TOKEN", bundle["app_token"]),
        ("SLACK_ALLOWED_USERS", bundle["allowed_users"]),
    ):
        _set_hermes_secret(name, value)
    bundle.clear()
    _send_secret_notice(
        "Slack tokens are saved on this Computer. The platform is refreshing "
        "Hermes now — I will confirm when Slack is ready."
    )
    _claim_handoff(
        client,
        platform_auth,
        handoff_id,
        installed=True,
        message=None,
        outcome=HANDOFF_OUTCOME_RESTART_PENDING,
        connection_metadata=metadata,
    )


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


def _validate_slack_credentials(bundle: dict[str, str]) -> dict[str, Any]:
    auth = _slack_api_call("auth.test", token=bundle["bot_token"])
    _slack_api_call("apps.connections.open", token=bundle["app_token"])
    for user_id in bundle["allowed_users"].split(","):
        _slack_api_call(
            "users.info",
            token=bundle["bot_token"],
            params={"user": user_id},
        )

    app_id = str(auth.get("app_id") or "").strip().upper()
    bot_id = str(auth.get("bot_id") or "").strip().upper()
    app_name = "Tinyhat Agent"
    if bot_id:
        bot = _slack_api_call(
            "bots.info",
            token=bundle["bot_token"],
            params={"bot": bot_id},
        ).get("bot")
        if isinstance(bot, dict):
            app_id = str(bot.get("app_id") or app_id).strip().upper()
            app_name = str(bot.get("name") or app_name).strip()[:80]
    if not SLACK_ID_RE.fullmatch(app_id):
        user_id = str(auth.get("user_id") or "").strip().upper()
        if user_id:
            user = _slack_api_call(
                "users.info",
                token=bundle["bot_token"],
                params={"user": user_id},
            ).get("user")
            profile = user.get("profile") if isinstance(user, dict) else None
            if isinstance(profile, dict):
                app_id = str(profile.get("api_app_id") or "").strip().upper()
    workspace_id = str(auth.get("team_id") or "").strip().upper()
    if not SLACK_ID_RE.fullmatch(app_id) or not SLACK_ID_RE.fullmatch(workspace_id):
        raise SecretHandoffError(
            "Slack did not return the app and workspace identifiers.",
            public_message="Slack accepted the tokens but did not identify the app.",
        )
    return {
        "provider": "slack",
        "app_id": app_id,
        "app_name": app_name,
        "workspace_id": workspace_id,
        "workspace_name": str(auth.get("team") or workspace_id).strip()[:100],
        "allowed_user_count": len(bundle["allowed_users"].split(",")),
    }


def _slack_api_call(
    method: str,
    *,
    token: str,
    params: dict[str, str] | None = None,
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
        raise SecretHandoffError(
            f"Slack API validation failed for {method}.",
            public_message="Slack could not validate these connection details.",
        ) from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        error_name = (
            str(payload.get("error") or "unknown_error")
            if isinstance(payload, dict)
            else "invalid_response"
        )
        raise SecretHandoffError(
            f"Slack rejected {method}: {error_name[:80]}.",
            public_message=(
                "Slack rejected one of the tokens or member IDs. Check the values "
                "in the Slack app settings and try again."
            ),
        )
    return payload
