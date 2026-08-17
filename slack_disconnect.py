"""Plugin-owned Slack revocation and complete local bundle removal."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

from .secret_handoff import WORKER_SYSTEMD_ENV_KEYS

SCHEMA = "tinyhat_plugin_slack_disconnect_v1"
SLACK_AUTH_REVOKE_URL = "https://slack.com/api/auth.revoke"
SLACK_ENV_NAMES = (
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "SLACK_ALLOWED_USERS",
    "SLACK_HOME_CHANNEL",
    "SLACK_HOME_CHANNEL_NAME",
)
ALREADY_REVOKED_ERRORS = frozenset(
    {
        "account_inactive",
        "invalid_auth",
        "not_authed",
        "token_expired",
        "token_revoked",
    }
)


def _revoke_slack_bot_access(token: str | None) -> dict[str, Any]:
    """Return only allowlisted provider state, never the token or raw body."""

    clean_token = str(token or "").strip()
    if not clean_token:
        return {"status": "not_present", "confirmed": False}
    api_request = request.Request(
        SLACK_AUTH_REVOKE_URL,
        data=b"",
        method="POST",
        headers={
            "Authorization": f"Bearer {clean_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with request.urlopen(api_request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, error.URLError):
        return {"status": "unconfirmed", "confirmed": False}
    if not isinstance(payload, dict):
        return {"status": "unconfirmed", "confirmed": False}
    if payload.get("ok") is True and payload.get("revoked") is True:
        return {"status": "revoked", "confirmed": True}
    error_code = str(payload.get("error") or "").strip()
    if error_code in ALREADY_REVOKED_ERRORS:
        return {
            "status": "already_revoked",
            "confirmed": True,
            "error_code": error_code,
        }
    return {"status": "unconfirmed", "confirmed": False}


def _runtime_helpers() -> tuple[Any, Any, Any, Any]:
    """Load the existing generic runtime env helpers without changing runtime."""

    runtime_prefix = os.getenv("TINYHAT_RUNTIME_PREFIX", "/opt/tinyhat-hermes-runtime").strip()
    if runtime_prefix and runtime_prefix not in sys.path:
        sys.path.insert(0, runtime_prefix)
    from hermes_runtime.runtime_env import (  # noqa: PLC0415
        env_file_candidates,
        read_env_values,
    )
    from hermes_runtime.terminal_env_passthrough import (  # noqa: PLC0415
        sync_terminal_env_passthrough,
    )
    from hermes_runtime.terminal_secret_aliases import (  # noqa: PLC0415
        force_alias_name,
    )

    return (
        env_file_candidates,
        read_env_values,
        sync_terminal_env_passthrough,
        force_alias_name,
    )


def _assignment_name(line: str) -> str | None:
    clean = line.strip()
    if not clean or clean.startswith("#") or "=" not in clean:
        return None
    if clean.startswith("export "):
        clean = clean[len("export ") :].lstrip()
    key, _, _value = clean.partition("=")
    return key.strip() or None


def _remove_names_from_env_file(
    path: Path,
    *,
    names: tuple[str, ...],
    force_alias_name: Any,
) -> bool:
    expanded = path.expanduser()
    try:
        before = expanded.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    removed_names = {candidate for name in names for candidate in (name, force_alias_name(name))}
    after_lines = [
        line for line in before.splitlines() if _assignment_name(line) not in removed_names
    ]
    after = "\n".join(after_lines).rstrip() + "\n"
    if after == before:
        return False
    expanded.write_text(after, encoding="utf-8")
    expanded.chmod(0o600)
    return True


def disconnect_slack_locally() -> dict[str, Any]:
    """Revoke Slack, remove the full local bundle, and return no secrets."""

    slack_access: dict[str, Any] = {"status": "unconfirmed", "confirmed": False}
    try:
        (
            env_file_candidates,
            read_env_values,
            sync_terminal_env_passthrough,
            force_alias_name,
        ) = _runtime_helpers()
        paths = env_file_candidates()
        values = read_env_values(paths, names=["SLACK_BOT_TOKEN"])
        token = os.environ.get("SLACK_BOT_TOKEN") or values.get("SLACK_BOT_TOKEN")
        slack_access = _revoke_slack_bot_access(token)
        if slack_access.get("status") == "unconfirmed":
            return {
                "schema": SCHEMA,
                "local_bundle_absent": False,
                "slack_access": slack_access,
                "failure_code": "slack_revoke_unconfirmed",
            }

        for path in paths:
            _remove_names_from_env_file(
                path,
                names=SLACK_ENV_NAMES,
                force_alias_name=force_alias_name,
            )
        process_names = {
            candidate for name in SLACK_ENV_NAMES for candidate in (name, force_alias_name(name))
        }
        for name in process_names:
            os.environ.pop(name, None)
        sync_terminal_env_passthrough([], remove_names=list(SLACK_ENV_NAMES))
        remaining = read_env_values(paths, names=list(SLACK_ENV_NAMES))
        local_bundle_absent = not any(name in remaining for name in SLACK_ENV_NAMES)
        if not local_bundle_absent:
            raise RuntimeError("Hermes still reports Slack configuration.")
        return {
            "schema": SCHEMA,
            "local_bundle_absent": True,
            "slack_access": slack_access,
        }
    except Exception:
        return {
            "schema": SCHEMA,
            "local_bundle_absent": False,
            "slack_access": slack_access,
            "failure_code": "local_bundle_removal_failed",
        }


def start_slack_disconnect_worker(state: dict[str, Any]) -> None:
    """Start a detached plugin worker that survives the initiating tool call."""

    handoff_id = str(state.get("handoff_id") or "").strip()
    removal_id = str(state.get("removal_id") or "").strip()
    expires_at = str(state.get("expires_at") or "").strip()
    if not handoff_id or not removal_id or not expires_at:
        raise RuntimeError("Platform did not return a complete disconnect request.")
    package_dir = Path(__file__).resolve().parent
    env = os.environ.copy()
    pythonpath = str(package_dir.parent)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONPATH"] = pythonpath
    args = [
        sys.executable,
        str(package_dir / "slack_disconnect_worker.py"),
        "--handoff-id",
        handoff_id,
        "--removal-id",
        removal_id,
        "--expires-at",
        expires_at,
    ]
    systemd_run = shutil.which("systemd-run")
    if systemd_run:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "-", removal_id).strip("-")[:48]
        command = [
            systemd_run,
            "--user",
            "--collect",
            "--quiet",
            f"--unit=tinyhat-slack-disconnect-{safe_id or 'worker'}",
        ]
        for key in WORKER_SYSTEMD_ENV_KEYS:
            if key in env:
                command.append(f"--setenv={key}={env[key]}")
        try:
            completed = subprocess.run(
                [*command, *args],
                cwd=str(package_dir.parent),
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        if completed is not None and completed.returncode == 0:
            return
    subprocess.Popen(
        args,
        cwd=str(package_dir.parent),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
