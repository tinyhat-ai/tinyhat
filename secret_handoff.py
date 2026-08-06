"""Private secret handoff tool implementation."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .hat_secrets import (
    HatSecretStoreError,
    ensure_hat_key_pair,
    list_hat_secret_names,
    normalize_hat_handle,
    normalize_secret_name,
    set_hat_secret,
    set_hat_secrets,
)
from .platform import (
    PlatformClient,
    PlatformError,
    build_platform_client,
    computer_api_path,
)
from .tool_errors import tool_error_json

KEY_ALGORITHM = "RSA-OAEP-256"
DEFAULT_EXPIRES_IN_SECONDS = 300
MAX_EXPIRES_IN_SECONDS = 30 * 60
SECRET_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,126}$")
STATE_DIR = Path.home() / ".tinyhat" / "private-secret-handoffs"
WORKER_SYSTEMD_ENV_KEYS = (
    "HOME",
    "PATH",
    "PYTHONPATH",
    "HERMES_BIN",
    "HERMES_ENV_FILE",
    "HERMES_PROJECT_DIR",
    "TINYHAT_HERMES_HOME",
    "TINYHAT_RUNTIME_PREFIX",
    "TINYHAT_PLATFORM_URL",
    "TINYHAT_LOCAL_DEV_TOKEN",
    "TINYHAT_COMPUTER_TOKEN_AUDIENCE",
)
HANDOFF_OUTCOME_RESTART_PENDING = "installed_restart_pending"
PRIVATE_SECRET_EXAMPLE_CALL = {
    "name": "EXA_API_KEY",
    "description": "Exa API key for web search and research tools.",
}
GENERIC_SECRET_NAMES = {
    "TINYHAT_SECRET",
    "SECRET",
    "API_KEY",
    "TOKEN",
    "PASSWORD",
    "CREDENTIAL",
    "WEBHOOK_SECRET",
}
RESERVED_SLACK_CONNECTION_NAMES = frozenset(
    {
        "SLACK_CONNECTION",
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "SLACK_ALLOWED_USERS",
    }
)
SECRET_NAME_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("exa", "exa.ai"), "EXA_API_KEY"),
    (("openrouter", "open router"), "OPENROUTER_API_KEY"),
    (("openai", "chatgpt"), "OPENAI_API_KEY"),
    (("anthropic", "claude"), "ANTHROPIC_API_KEY"),
    (("github", "git hub"), "GITHUB_TOKEN"),
    (("stripe",), "STRIPE_SECRET_KEY"),
    (("tavily",), "TAVILY_API_KEY"),
    (("firecrawl", "fire crawl"), "FIRECRAWL_API_KEY"),
    (("perplexity",), "PERPLEXITY_API_KEY"),
    (("serper",), "SERPER_API_KEY"),
    (("deepseek", "deep seek"), "DEEPSEEK_API_KEY"),
    (("gemini", "google ai", "google/gemini"), "GEMINI_API_KEY"),
    (("xai", "grok"), "XAI_API_KEY"),
    (("slack",), "SLACK_BOT_TOKEN"),
    (("telegram",), "TELEGRAM_BOT_TOKEN"),
    (("resend",), "RESEND_API_KEY"),
    (("elevenlabs", "eleven labs"), "ELEVENLABS_API_KEY"),
    (("browserbase", "browser base"), "BROWSERBASE_API_KEY"),
    (("fal", "fal.ai"), "FAL_API_KEY"),
)


class SecretHandoffError(RuntimeError):
    """The private secret handoff could not start or finish."""

    def __init__(self, message: str, *, public_message: str | None = None) -> None:
        super().__init__(message)
        self.public_message = public_message or "Could not start secure secret entry."


def start_private_secret_handoff(
    args: dict[str, Any] | None = None,
    **_: Any,
) -> str:
    """Hermes tool handler that starts one private secret handoff."""
    payload = args if isinstance(args, dict) else {}
    raw_secret_name = payload.get("name")
    description = _clean_description(payload.get("description"))
    missing = []
    if not str(raw_secret_name or "").strip():
        missing.append("name")
    if not description:
        missing.append("description")
    if missing:
        return tool_error_json(
            tool="tinyhat_private_secret_handoff",
            error_name="missing_required_parameter",
            message=(
                "Call tinyhat_private_secret_handoff with a specific env-style "
                "secret name and a short description. Do not ask the user to "
                "paste the secret in chat."
            ),
            missing=missing,
            example_call=PRIVATE_SECRET_EXAMPLE_CALL,
        )

    secret_name = _resolve_secret_name(raw_secret_name, description)
    if secret_name in RESERVED_SLACK_CONNECTION_NAMES:
        return tool_error_json(
            tool="tinyhat_private_secret_handoff",
            error_name="slack_connection_required",
            message=(
                "Slack connection values are managed as one Hermes Socket Mode "
                "bundle. Load tinyhat:tinyhat-slack and call "
                "tinyhat_slack_connect once."
            ),
        )
    expires_in_seconds = DEFAULT_EXPIRES_IN_SECONDS

    prepared = _request_private_secret_handoff(
        payload=payload,
        secret_name=secret_name,
        description=description,
        expires_in_seconds=expires_in_seconds,
    )
    if isinstance(prepared, str):
        return prepared
    handoff, private_key_pem, hat_handle = prepared
    if not handoff.get("existing_handoff"):
        if hat_handle:
            _start_worker_process(handoff, private_key_pem, hat_handle=hat_handle)
        else:
            _start_worker_process(handoff, private_key_pem)
    shown_name = str(handoff.get("secret_name") or secret_name)
    return (
        f"I sent the secure Enter secret button for `{shown_name}`. Tap it "
        "within about 5 minutes and paste the value there. Tinyhat never sees "
        "the plaintext."
    )


def start_hat_credentials_handoff(hat_identifier: str) -> str:
    """Open one encrypted browser form for every credential defined by a Hat."""
    client, platform_auth = build_platform_client()
    try:
        detail_path = computer_api_path(platform_auth, "hats/v1/detail")
        hat = client.get_json(f"{detail_path}?{urlencode({'identifier': hat_identifier})}")
        hat_handle = normalize_hat_handle(str(hat.get("handle") or ""))
        credentials_path = computer_api_path(platform_auth, "hats/v1/credentials")
        listed = client.get_json(f"{credentials_path}?{urlencode({'identifier': hat_handle})}")
        credentials = listed.get("credentials")
        if not isinstance(credentials, list) or not credentials:
            return tool_error_json(
                tool="tinyhat_hats",
                error_name="hat_credentials_empty",
                message=(
                    "Define at least one credential name and description for this "
                    "Hat before opening secure entry."
                ),
            )
        private_key_path, public_key_pem = _hat_credentials_key_pair(hat_handle)
        defined_names = {
            normalize_secret_name(str(item.get("name") or ""))
            for item in credentials
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }
        local_names = set(list_hat_secret_names(hat_handle)["names"])
        bundle_name = (
            "HAT_CREDENTIALS_" + hashlib.sha256(hat_handle.encode("utf-8")).hexdigest()[:12].upper()
        )
        handoff = client.post_json(
            computer_api_path(platform_auth, "private-secret-handoffs/v1"),
            {
                "name": bundle_name,
                "description": f"Credentials for {hat_handle}",
                "public_key_pem": public_key_pem,
                "key_algorithm": KEY_ALGORITHM,
                "expires_in_seconds": DEFAULT_EXPIRES_IN_SECONDS,
                "handoff_kind": "hat_credentials",
                "hat_identifier": hat_handle,
                "existing_credential_names": sorted(defined_names & local_names),
            },
        )
    except (PlatformError, HatSecretStoreError, OSError) as exc:
        return tool_error_json(
            tool="tinyhat_hats",
            error_name="hat_credentials_handoff_failed",
            message=f"Could not open the encrypted Hat credentials page: {exc}",
        )

    _start_worker_process(
        handoff,
        private_key_path.read_text(encoding="utf-8"),
        hat_handle=hat_handle,
        persistent=True,
        key_path=private_key_path,
    )
    count = len(handoff.get("credentials") or credentials)
    return (
        f"I sent one secure Enter credentials button for {count} Hat "
        f"credential{'s' if count != 1 else ''}. Edit the values together on that page; "
        "saved values can stay blank when they should be kept. "
        "They are encrypted together and staged only in the Hat's local package "
        "store for its intended customer. They are not loaded into this agent's "
        "Hermes environment, so Hermes is not restarted."
    )


def _request_private_secret_handoff(
    *,
    payload: dict[str, Any],
    secret_name: str,
    description: str,
    expires_in_seconds: int,
) -> tuple[dict[str, Any], str, str | None] | str:
    """Resolve the value-blind target and create one bound handoff."""
    private_key_pem, public_key_pem = _generate_key_pair()
    client, platform_auth = build_platform_client()
    hat_identifier = str(payload.get("hat_identifier") or "").strip()
    hat_handle: str | None = None
    if hat_identifier:
        try:
            hat = client.get_json(
                f"{computer_api_path(platform_auth, 'hats/v1/detail')}?"
                f"{urlencode({'identifier': hat_identifier})}"
            )
            hat_handle = normalize_hat_handle(str(hat.get("handle") or ""))
        except (PlatformError, HatSecretStoreError):
            return tool_error_json(
                tool="tinyhat_private_secret_handoff",
                error_name="hat_not_found",
                message=(
                    f"I could not find the Hat `{hat_identifier}` for this owner. "
                    "Call tinyhat_hats with action=list and retry with its canonical "
                    "handle."
                ),
                expected={"hat_identifier": "owner/hats/hat-key"},
            )
    try:
        handoff = client.post_json(
            computer_api_path(platform_auth, "private-secret-handoffs/v1"),
            {
                "name": secret_name,
                "description": description,
                "public_key_pem": public_key_pem,
                "key_algorithm": KEY_ALGORITHM,
                "expires_in_seconds": expires_in_seconds,
                **({"hat_identifier": hat_handle} if hat_handle else {}),
            },
        )
    except PlatformError as exc:
        return tool_error_json(
            tool="tinyhat_private_secret_handoff",
            error_name="handoff_request_failed",
            message=(
                "Could not start this secure entry. If another entry for this "
                "credential is pending, finish it or let it expire before retrying. "
                f"Platform response: {exc}"
            ),
        )

    effective_hat_handle: str | None = None
    try:
        if str(handoff.get("hat_handle") or "").strip():
            effective_hat_handle = normalize_hat_handle(str(handoff["hat_handle"]))
    except HatSecretStoreError:
        effective_hat_handle = None
    # The platform deduplicates pending handoffs only when connection metadata
    # matches. Verify its value-blind echo as a second boundary before reusing
    # the first call's already-running worker.
    if effective_hat_handle != hat_handle:
        return tool_error_json(
            tool="tinyhat_private_secret_handoff",
            error_name="handoff_binding_mismatch",
            message=(
                "The pending secure entry targets a different destination. "
                "Finish it or let it expire, then retry for this Hat."
            ),
            expected={"hat_identifier": hat_handle or "computer"},
        )
    return handoff, private_key_pem, hat_handle


def _start_worker_process(
    handoff: dict[str, Any],
    private_key_pem: str,
    *,
    hat_handle: str | None = None,
    persistent: bool = False,
    key_path: Path | None = None,
) -> None:
    handoff_id = str(handoff.get("handoff_id") or "").strip()
    if not handoff_id:
        raise SecretHandoffError("Platform did not return a handoff id.")
    expires_in_seconds = _worker_expires_in_seconds(handoff)
    worker_key_path = key_path or _write_private_key_file(handoff_id, private_key_pem)
    package_dir = Path(__file__).resolve().parent
    env = os.environ.copy()
    pythonpath = str(package_dir.parent)
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONPATH"] = pythonpath
    try:
        if _start_worker_with_systemd(
            handoff_id=handoff_id,
            key_path=worker_key_path,
            package_dir=package_dir,
            env=env,
            expires_in_seconds=expires_in_seconds,
            hat_handle=hat_handle,
            persistent=persistent,
        ):
            return
        _start_worker_with_popen(
            handoff_id=handoff_id,
            key_path=worker_key_path,
            package_dir=package_dir,
            env=env,
            expires_in_seconds=expires_in_seconds,
            hat_handle=hat_handle,
            persistent=persistent,
        )
    except Exception as exc:
        if not persistent:
            with suppress(OSError):
                worker_key_path.unlink()
        raise SecretHandoffError(
            "Could not start the local secret handoff worker.",
            public_message="I could not start the secure secret saver on this Computer.",
        ) from exc


def _worker_expires_in_seconds(handoff: dict[str, Any]) -> int:
    raw_value = handoff.get("entry_window_seconds")
    if raw_value is None:
        raw_value = handoff.get("expires_in_seconds")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = DEFAULT_EXPIRES_IN_SECONDS
    return min(max(1, value), MAX_EXPIRES_IN_SECONDS)


def _start_worker_with_systemd(  # noqa: PLR0913 - explicit worker boundary inputs
    *,
    handoff_id: str,
    key_path: Path,
    package_dir: Path,
    env: dict[str, str],
    expires_in_seconds: int,
    hat_handle: str | None = None,
    persistent: bool = False,
) -> bool:
    systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        return False
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "-", handoff_id).strip("-")[:48] or "secret"
    command = [
        systemd_run,
        "--user",
        "--collect",
        "--quiet",
        f"--unit=tinyhat-secret-handoff-{safe_id}",
    ]
    for key in WORKER_SYSTEMD_ENV_KEYS:
        if key in env:
            command.append(f"--setenv={key}={env[key]}")
    command.extend(
        [
            sys.executable,
            str(package_dir / "secret_handoff_worker.py"),
            "--handoff-id",
            handoff_id,
            "--key-path",
            str(key_path),
            "--expires-in-seconds",
            str(expires_in_seconds),
        ]
    )
    if hat_handle:
        command.extend(["--hat-handle", hat_handle])
    if persistent:
        command.append("--persistent")
    try:
        completed = subprocess.run(
            command,
            cwd=str(package_dir.parent),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _log_worker_spawn_fallback(str(exc)[:500])
        return False
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "systemd-run failed").strip()
        _log_worker_spawn_fallback(detail[:500])
        return False
    return True


def _log_worker_spawn_fallback(detail: str) -> None:
    print(
        "tinyhat-secret-handoff: systemd-run worker spawn failed, "
        f"falling back to a detached process: {detail}",
        file=sys.stderr,
    )


def _start_worker_with_popen(  # noqa: PLR0913 - mirrors the systemd worker inputs
    *,
    handoff_id: str,
    key_path: Path,
    package_dir: Path,
    env: dict[str, str],
    expires_in_seconds: int,
    hat_handle: str | None = None,
    persistent: bool = False,
) -> None:
    # Fallback when systemd-run is unavailable or fails. The worker never
    # stops or starts the gateway, so escaping the gateway control group via
    # systemd-run above is defense in depth, not load-bearing.
    command = [
        sys.executable,
        str(package_dir / "secret_handoff_worker.py"),
        "--handoff-id",
        handoff_id,
        "--key-path",
        str(key_path),
        "--expires-in-seconds",
        str(expires_in_seconds),
    ]
    if hat_handle:
        command.extend(["--hat-handle", hat_handle])
    if persistent:
        command.append("--persistent")
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


def _write_private_key_file(handoff_id: str, private_key_pem: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", handoff_id)
    directory = STATE_DIR / safe_id
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    key_path = directory / "private.pem"
    key_path.write_text(private_key_pem, encoding="utf-8")
    key_path.chmod(0o600)
    return key_path


def _hat_credentials_key_pair(hat_handle: str) -> tuple[Path, str]:
    """Return the stable Computer-local key pair for one Hat bundle."""
    return ensure_hat_key_pair(hat_handle, key_pair_factory=_generate_key_pair)


def _poll_and_install_secret(
    *,
    client: PlatformClient,
    platform_auth: str,
    handoff: dict[str, Any],
    private_key_pem: str,
) -> None:
    handoff_id = str(handoff.get("handoff_id") or "").strip()
    if not handoff_id:
        return
    try:
        deadline = _parse_expires_at(handoff.get("expires_at")) or (
            time.time() + DEFAULT_EXPIRES_IN_SECONDS
        )
        poll_after = max(1.0, float(handoff.get("poll_after_ms") or 2000) / 1000)
        last_status = ""
        last_handoff_kind = ""
        while time.time() < deadline:
            state = client.get_json(
                computer_api_path(platform_auth, f"private-secret-handoffs/v1/{handoff_id}")
            )
            status = str(state.get("status") or "").strip()
            last_status = status
            last_handoff_kind = str(state.get("handoff_kind") or "").strip()
            if status == "submitted":
                installed = _install_submitted_secret(
                    client=client,
                    platform_auth=platform_auth,
                    handoff_id=handoff_id,
                    private_key_pem=private_key_pem,
                    state=state,
                )
                if installed:
                    return
            if status in {"claimed", "expired"}:
                return
            if status == "failed" and state.get("handoff_kind") != "slack_connection":
                return
            time.sleep(poll_after)
        if last_status == "failed" and last_handoff_kind == "slack_connection":
            return
        _claim_handoff(
            client,
            platform_auth,
            handoff_id,
            installed=False,
            message="Secret entry expired before a value was submitted.",
        )
    except Exception as exc:  # pragma: no cover - worker safety net
        try:
            _claim_handoff(
                client,
                platform_auth,
                handoff_id,
                installed=False,
                message=_public_failure_message(exc),
            )
        except Exception:
            pass


def _install_submitted_secret(  # noqa: PLR0913 - generic, Slack, and Hat installer
    *,
    client: PlatformClient,
    platform_auth: str,
    handoff_id: str,
    private_key_pem: str,
    state: dict[str, Any],
    hat_handle: str | None = None,
) -> bool:
    if state.get("handoff_kind") == "slack_connection":
        from .slack_connection import install_submitted_slack_connection

        return install_submitted_slack_connection(
            client=client,
            platform_auth=platform_auth,
            handoff_id=handoff_id,
            private_key_pem=private_key_pem,
            state=state,
        )
    if state.get("handoff_kind") == "hat_credentials":
        return _install_hat_credentials_bundle(
            client=client,
            platform_auth=platform_auth,
            handoff_id=handoff_id,
            private_key_pem=private_key_pem,
            state=state,
            hat_handle=hat_handle,
        )
    ciphertext_payload = state.get("ciphertext_payload")
    if not isinstance(ciphertext_payload, dict):
        raise SecretHandoffError("Platform did not return ciphertext.")
    secret_name = _normalize_secret_name(str(state.get("secret_name") or ""))
    if secret_name in RESERVED_SLACK_CONNECTION_NAMES:
        raise SecretHandoffError(
            "Reserved Slack connection value reached the generic secret installer.",
            public_message=(
                "Use the Connect Slack flow so Hermes can validate and save "
                "the complete Socket Mode connection."
            ),
        )
    requested_hat_handle = normalize_hat_handle(hat_handle) if hat_handle else None
    state_hat_handle = (
        normalize_hat_handle(str(state.get("hat_handle") or ""))
        if str(state.get("hat_handle") or "").strip()
        else None
    )
    if requested_hat_handle and state_hat_handle not in {None, requested_hat_handle}:
        raise SecretHandoffError(
            "Platform returned a different Hat binding for this handoff.",
            public_message="The secure entry no longer matches the requested Hat.",
        )
    effective_hat_handle = requested_hat_handle or state_hat_handle
    plaintext = _decrypt_ciphertext(private_key_pem, ciphertext_payload)
    try:
        if effective_hat_handle:
            set_hat_secret(effective_hat_handle, secret_name, plaintext)
        else:
            _set_hermes_secret(secret_name, plaintext)
    finally:
        plaintext = ""
    if effective_hat_handle:
        client.post_json(
            computer_api_path(platform_auth, "hats/v1/credentials"),
            {
                "identifier": effective_hat_handle,
                "name": secret_name,
                "description": str(state.get("description") or "").strip() or None,
            },
        )
        _claim_handoff(
            client,
            platform_auth,
            handoff_id,
            installed=True,
            message=None,
        )
        return True
    _register_terminal_env_secret(secret_name)
    _send_secret_available_notice(secret_name)
    # The platform owns the gateway restart: on this claim it queues the
    # runtime's one-shot restart command and sends the final ready-or-failed
    # confirmation after that command settles. The worker never stops,
    # starts, or restarts the gateway.
    _claim_handoff(
        client,
        platform_auth,
        handoff_id,
        installed=True,
        message=None,
        outcome=HANDOFF_OUTCOME_RESTART_PENDING,
    )
    return True


def _install_hat_credentials_bundle(  # noqa: PLR0913 - explicit trust boundary
    *,
    client: PlatformClient,
    platform_auth: str,
    handoff_id: str,
    private_key_pem: str,
    state: dict[str, Any],
    hat_handle: str | None,
) -> bool:
    ciphertext_payload = state.get("ciphertext_payload")
    if not isinstance(ciphertext_payload, dict):
        raise SecretHandoffError("Platform did not return ciphertext.")
    requested_handle = normalize_hat_handle(str(hat_handle or ""))
    state_handle = normalize_hat_handle(str(state.get("hat_handle") or ""))
    if requested_handle != state_handle:
        raise SecretHandoffError(
            "Platform returned a different Hat binding for this bundle.",
            public_message="The secure entry no longer matches the requested Hat.",
        )
    expected_credentials = state.get("credentials")
    if not isinstance(expected_credentials, list) or not expected_credentials:
        raise SecretHandoffError("Platform did not return Hat credential metadata.")
    expected_names = {
        normalize_secret_name(str(item.get("name") or ""))
        for item in expected_credentials
        if isinstance(item, dict)
    }
    plaintext = _decrypt_ciphertext(private_key_pem, ciphertext_payload)
    values: dict[str, str] = {}
    try:
        bundle = json.loads(plaintext)
        if (
            not isinstance(bundle, dict)
            or bundle.get("schema") != "tinyhat_hat_credentials_bundle_v1"
            or not isinstance(bundle.get("credentials"), dict)
        ):
            raise SecretHandoffError("The Hat credential bundle is invalid.")
        values = {
            normalize_secret_name(str(name)): str(value)
            for name, value in bundle["credentials"].items()
        }
        submitted_names = set(values)
        if not submitted_names or not submitted_names.issubset(expected_names):
            raise SecretHandoffError("The Hat credential bundle does not match the expected names.")
        saved_names = set(list_hat_secret_names(requested_handle)["names"])
        missing_names = expected_names - submitted_names
        if not missing_names.issubset(saved_names):
            raise SecretHandoffError(
                "The Hat credential bundle omitted a credential without a saved value.",
                public_message=(
                    "One or more blank credentials do not have a saved value. "
                    "Open the form again and enter them."
                ),
            )
        set_hat_secrets(requested_handle, values)
    finally:
        plaintext = ""
        values.clear()
    _claim_handoff(
        client,
        platform_auth,
        handoff_id,
        installed=True,
        message=None,
        gateway_ready=True,
    )
    return True


def _claim_handoff(
    client: PlatformClient,
    platform_auth: str,
    handoff_id: str,
    *,
    installed: bool,
    message: str | None = None,
    gateway_ready: bool | None = None,
    outcome: str | None = None,
    connection_metadata: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {"installed": installed, "message": message}
    if gateway_ready is not None:
        payload["gateway_ready"] = gateway_ready
    if outcome:
        payload["outcome"] = outcome
    if connection_metadata is not None:
        payload["connection_metadata"] = connection_metadata
    path = computer_api_path(
        platform_auth,
        f"private-secret-handoffs/v1/{handoff_id}/claim",
    )
    try:
        client.post_json(path, payload)
        return
    except Exception:
        if connection_metadata is not None:
            raise
        if gateway_ready is None and not outcome:
            raise

    client.post_json(
        path,
        _legacy_claim_payload(installed=installed, message=message),
    )


def _legacy_claim_payload(*, installed: bool, message: str | None) -> dict[str, Any]:
    return {"installed": installed, "message": message}


def _generate_key_pair() -> tuple[str, str]:
    openssl = shutil.which("openssl")
    if not openssl:
        raise SecretHandoffError("openssl is required for private secret handoffs.")
    with tempfile.TemporaryDirectory(prefix="tinyhat-secret-") as temp_dir:
        private_key = Path(temp_dir) / "private.pem"
        public_key = Path(temp_dir) / "public.pem"
        _run([openssl, "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", str(private_key)])
        _run([openssl, "rsa", "-pubout", "-in", str(private_key), "-out", str(public_key)])
        return (
            private_key.read_text(encoding="utf-8"),
            public_key.read_text(encoding="utf-8"),
        )


def _decrypt_ciphertext(private_key_pem: str, payload: dict[str, Any]) -> str:
    if payload.get("algorithm") != KEY_ALGORITHM:
        raise SecretHandoffError("Unsupported ciphertext algorithm.")
    chunks = payload.get("ciphertext_chunks_b64")
    if isinstance(chunks, list) and chunks:
        plaintext_parts = [
            _decrypt_one_chunk(private_key_pem, str(chunk or "").strip())
            for chunk in chunks
        ]
        return b"".join(plaintext_parts).decode("utf-8")
    ciphertext_b64 = str(payload.get("ciphertext_b64") or "").strip()
    if not ciphertext_b64:
        raise SecretHandoffError("Ciphertext payload is empty.")
    return _decrypt_one_chunk(private_key_pem, ciphertext_b64).decode("utf-8")


def _decrypt_one_chunk(private_key_pem: str, ciphertext_b64: str) -> bytes:
    if not ciphertext_b64:
        raise SecretHandoffError("Ciphertext chunk is empty.")
    openssl = shutil.which("openssl")
    if not openssl:
        raise SecretHandoffError("openssl is required for private secret handoffs.")
    with tempfile.TemporaryDirectory(prefix="tinyhat-secret-") as temp_dir:
        private_key = Path(temp_dir) / "private.pem"
        ciphertext_path = Path(temp_dir) / "secret.bin"
        private_key.write_text(private_key_pem, encoding="utf-8")
        private_key.chmod(0o600)
        ciphertext_path.write_bytes(base64.b64decode(ciphertext_b64))
        result = _run(
            [
                openssl,
                "pkeyutl",
                "-decrypt",
                "-inkey",
                str(private_key),
                "-in",
                str(ciphertext_path),
                "-pkeyopt",
                "rsa_padding_mode:oaep",
                "-pkeyopt",
                "rsa_oaep_md:sha256",
            ],
            text=False,
        )
        return result


def _set_hermes_secret(secret_name: str, value: str) -> None:
    hermes = shutil.which("hermes")
    if not hermes:
        raise SecretHandoffError(
            "Hermes CLI was not found.",
            public_message="Hermes could not save this secret.",
        )
    try:
        if _can_save_with_hermes_config_set(secret_name):
            _run([hermes, "config", "set", secret_name, value], redactions=(value,))
        else:
            _save_hermes_env_value(hermes, secret_name, value)
    except SecretHandoffError as exc:
        raise SecretHandoffError(
            "Hermes config could not save this secret.",
            public_message="Hermes could not save this secret.",
        ) from exc
    try:
        _reload_hermes_env_current_process(hermes, secret_name)
    except Exception:
        pass


def _register_terminal_env_secret(secret_name: str) -> dict[str, Any]:
    """Ask the Tinyhat runtime to expose this secret to Hermes terminals.

    Hermes owns the security boundary for terminal/code subprocess env values.
    The runtime receives only the secret name, records Hermes terminal config,
    and maintains Tinyhat-managed local-terminal aliases for names that Hermes
    otherwise protects as provider/tool credentials. Best effort: registration
    must not fail saving the secret for Hermes' main-process tools.
    """
    runtime_prefix = os.getenv("TINYHAT_RUNTIME_PREFIX", "/opt/tinyhat-hermes-runtime")
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{runtime_prefix}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else runtime_prefix
    )
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "hermes_runtime.terminal_env_passthrough",
                "register",
                secret_name,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)[:200]}
    if completed.returncode != 0:
        return {
            "ok": False,
            "error": (completed.stderr or completed.stdout or "register failed")
            .strip()[:200],
        }
    return {"ok": True}


def _send_secret_available_notice(secret_name: str) -> dict[str, Any]:
    return _send_secret_notice(
        (
            f"{secret_name} is saved. The platform is refreshing my Telegram "
            "gateway now — I will confirm when it is ready."
        )
    )


def _send_secret_notice(text: str) -> dict[str, Any]:
    try:
        from .tools import _telegram_credentials, _telegram_send_message

        token, chat_id = _telegram_credentials()
        sent = _telegram_send_message(
            token=token,
            chat_id=chat_id,
            text=text,
        )
        return {"sent": bool(sent.get("ok")), "ok": bool(sent.get("ok"))}
    except Exception as exc:
        return {"sent": False, "ok": False, "error": str(exc)[:200]}


def _can_save_with_hermes_config_set(secret_name: str) -> bool:
    return (
        secret_name.endswith(("_API_KEY", "_TOKEN"))
        or secret_name.startswith("TERMINAL_SSH")
        or secret_name
        in {
            "FAL_KEY",
            "SUDO_PASSWORD",
        }
    )


def _reload_hermes_env_current_process(hermes: str, secret_name: str) -> dict[str, Any]:
    """Best-effort reload for the short-lived worker process.

    The worker exits after claiming the handoff, so this reload is diagnostic
    only. A failed worker-local reload must not turn a successful secret write
    into an install failure; the runtime restart owns the durable reload path.
    """
    loader_error: Exception | None = None
    try:
        from hermes_cli.config import reload_env

        reload_env()
    except Exception as exc:  # pragma: no cover - depends on Hermes install shape
        loader_error = exc
    if secret_name in os.environ:
        return {"ok": True, "source": "hermes_cli.config.reload_env"}

    env_path = _hermes_env_path(hermes)
    value = _read_env_value(env_path, secret_name)
    if value is not None:
        os.environ[secret_name] = value
        return {"ok": True, "source": str(env_path)}

    message = "Hermes env reload did not make this secret available."
    if loader_error is not None:
        return {"ok": False, "error": message, "loader_error": str(loader_error)[:200]}
    return {"ok": False, "error": message}


def _hermes_env_path(hermes: str) -> Path:
    explicit = os.getenv("HERMES_ENV_FILE")
    if explicit:
        return Path(explicit).expanduser()
    try:
        completed = subprocess.run(
            [hermes, "config", "env-path"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            return Path(completed.stdout.strip()).expanduser()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return Path.home() / ".hermes" / ".env"


def _read_env_value(path: Path, secret_name: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        clean = line.strip()
        if not clean or clean.startswith("#") or "=" not in clean:
            continue
        key, raw_value = clean.split("=", 1)
        if key.strip() != secret_name:
            continue
        return _parse_env_value(raw_value.strip())
    return None


def _parse_env_value(raw_value: str) -> str:
    if len(raw_value) >= 2 and raw_value[0] == raw_value[-1]:
        quote = raw_value[0]
        if quote == "'":
            return raw_value[1:-1]
        if quote == '"':
            return raw_value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return raw_value.split(" #", 1)[0].strip()


def _save_hermes_env_value(hermes: str, secret_name: str, value: str) -> None:
    python = _hermes_python_executable(hermes)
    if not python:
        raise SecretHandoffError("Could not find Hermes' Python runtime.")
    script = (
        "import sys\n"
        "from hermes_cli.config import save_env_value\n"
        "save_env_value(sys.argv[1], sys.stdin.read())\n"
    )
    _run([python, "-c", script, secret_name], input_text=value, redactions=(value,))


def _hermes_python_executable(hermes: str) -> str | None:
    scripts = _hermes_script_candidates(Path(hermes))
    candidates: list[Path] = []

    for script in scripts:
        candidates.extend(_hermes_wrapper_python_candidates(script))
    candidates.extend(_hermes_project_python_candidates())

    for script in scripts:
        shebang = _read_first_line(script)
        if not shebang.startswith("#!"):
            continue
        try:
            parts = shlex.split(shebang[2:].strip())
        except ValueError:
            continue
        if not parts:
            continue
        executable = Path(parts[0])
        if executable.name.startswith("python"):
            candidates.append(executable)
        elif executable.name == "env" and len(parts) > 1 and parts[1].startswith("python"):
            python = shutil.which(parts[1])
            if python:
                candidates.append(Path(python))

    for script in scripts:
        for name in ("python", "python3"):
            candidates.append(script.parent / name)

    seen: set[str] = set()
    for python in candidates:
        expanded = python.expanduser()
        key = str(expanded)
        if key in seen:
            continue
        seen.add(key)
        if expanded.exists() and _python_can_import_hermes_cli(expanded):
            return key
    return None


def _hermes_wrapper_python_candidates(hermes: Path) -> list[Path]:
    try:
        text = hermes.read_text(encoding="utf-8", errors="ignore")[:8192]
    except OSError:
        return []

    candidates: list[Path] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line, comments=True)
        except ValueError:
            continue
        while parts and parts[0] in {"command", "exec"}:
            parts.pop(0)
        if parts and Path(parts[0]).name == "env":
            parts.pop(0)
            while parts and "=" in parts[0] and not parts[0].startswith(("/", "~")):
                parts.pop(0)
        if not parts:
            continue
        raw_executable = os.path.expandvars(parts[0])
        executable = Path(raw_executable).expanduser()
        if not executable.name.startswith("python"):
            continue
        if not executable.is_absolute():
            resolved = shutil.which(raw_executable)
            if not resolved:
                continue
            executable = Path(resolved)
        if executable not in candidates:
            candidates.append(executable)
    return candidates


def _hermes_project_python_candidates() -> list[Path]:
    roots: list[Path] = []
    explicit = (os.getenv("HERMES_PROJECT_DIR") or "").strip()
    if explicit:
        roots.append(Path(explicit).expanduser())
    roots.extend(
        [
            Path("/usr/local/lib/hermes-agent"),
            Path.home() / ".hermes" / "hermes-agent",
        ]
    )

    candidates: list[Path] = []
    for root in roots:
        for relative in (
            Path("venv/bin/python"),
            Path(".venv/bin/python"),
            Path("venv/Scripts/python.exe"),
            Path(".venv/Scripts/python.exe"),
        ):
            python = root / relative
            if python not in candidates:
                candidates.append(python)
    return candidates


def _python_can_import_hermes_cli(python: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(python), "-c", "import hermes_cli.config"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _hermes_script_candidates(hermes: Path) -> list[Path]:
    candidates: list[Path] = []
    try:
        text = hermes.read_text(encoding="utf-8", errors="ignore")[:8192]
    except OSError:
        return [hermes]
    for match in re.finditer(r"""["']([^"']*/hermes(?:\.exe)?)["']""", text):
        candidate = Path(match.group(1))
        if candidate.exists() and candidate not in candidates:
            candidates.append(candidate)
    if hermes not in candidates:
        candidates.append(hermes)
    return candidates


def _read_first_line(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return handle.readline().strip()
    except OSError:
        return ""


def _run(
    command: list[str],
    *,
    text: bool = True,
    input_text: str | None = None,
    redactions: tuple[str, ...] = (),
) -> str | bytes:
    result = subprocess.run(
        command,
        capture_output=True,
        text=text,
        input=input_text,
        timeout=45,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        for value in redactions:
            if value:
                stderr = stderr.replace(value, "[redacted]")
        raise SecretHandoffError((stderr or "command failed").strip()[:500])
    return result.stdout if text else result.stdout


def _public_failure_message(exc: BaseException) -> str:
    if isinstance(exc, SecretHandoffError):
        return exc.public_message[:500]
    if isinstance(exc, UnicodeDecodeError):
        return "The encrypted secret could not be decoded."
    return "Could not complete secure secret entry."


def _parse_expires_at(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(
            timezone.utc
        ).timestamp()
    except ValueError:
        return None


def _normalize_secret_name(value: str) -> str:
    name = str(value or "").strip().upper()
    if not SECRET_NAME_RE.fullmatch(name):
        raise SecretHandoffError("Secret names must look like OPENROUTER_API_KEY.")
    return name


def _resolve_secret_name(value: Any, description: str | None) -> str:
    raw = str(value or "").strip()
    inferred = _infer_secret_name(
        " ".join(part for part in (raw, description or "") if part)
    )
    if not raw:
        if inferred:
            return inferred
        raise SecretHandoffError(
            "Choose a specific secret name like EXA_API_KEY or GITHUB_TOKEN."
        )

    try:
        name = _normalize_secret_name(raw)
    except SecretHandoffError:
        if inferred:
            return inferred
        raise

    if name in GENERIC_SECRET_NAMES:
        if inferred and inferred not in GENERIC_SECRET_NAMES:
            return inferred
        raise SecretHandoffError(
            "Secret names must be specific, for example EXA_API_KEY instead of TINYHAT_SECRET."
        )
    return name


def _infer_secret_name(text: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
    if not normalized:
        return None
    padded = f" {normalized} "
    for hints, name in SECRET_NAME_HINTS:
        if any(f" {hint} " in padded for hint in hints):
            return name
    return None


def _clean_description(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:500] if text else None
