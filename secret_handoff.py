"""Private secret handoff tool implementation."""

from __future__ import annotations

import base64
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .platform import PlatformClient, build_platform_client, computer_api_path
from .tool_errors import tool_error_json

KEY_ALGORITHM = "RSA-OAEP-256"
DEFAULT_EXPIRES_IN_SECONDS = 300
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

    private_key_pem, public_key_pem = _generate_key_pair()
    client, platform_auth = build_platform_client()
    handoff = client.post_json(
        computer_api_path(platform_auth, "private-secret-handoffs/v1"),
        {
            "name": secret_name,
            "description": description,
            "public_key_pem": public_key_pem,
            "key_algorithm": KEY_ALGORITHM,
            "expires_in_seconds": expires_in_seconds,
        },
    )
    if not handoff.get("existing_handoff"):
        _start_worker_process(handoff, private_key_pem)
    shown_name = str(handoff.get("secret_name") or secret_name)
    return (
        f"I sent the secure Enter secret button for `{shown_name}`. Tap it "
        "within about 5 minutes and paste the value there. Tinyhat never sees "
        "the plaintext."
    )

def _start_worker_process(handoff: dict[str, Any], private_key_pem: str) -> None:
    handoff_id = str(handoff.get("handoff_id") or "").strip()
    if not handoff_id:
        raise SecretHandoffError("Platform did not return a handoff id.")
    key_path = _write_private_key_file(handoff_id, private_key_pem)
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
        try:
            key_path.unlink()
        except OSError:
            pass
        raise SecretHandoffError(
            "Could not start the local secret handoff worker.",
            public_message="I could not start the secure secret saver on this Computer.",
        ) from exc


def _start_worker_with_systemd(
    *,
    handoff_id: str,
    key_path: Path,
    package_dir: Path,
    env: dict[str, str],
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
        ]
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


def _start_worker_with_popen(
    *,
    handoff_id: str,
    key_path: Path,
    package_dir: Path,
    env: dict[str, str],
) -> None:
    # Fallback when systemd-run is unavailable or fails. The worker never
    # stops or starts the gateway, so escaping the gateway control group via
    # systemd-run above is defense in depth, not load-bearing.
    subprocess.Popen(
        [
            sys.executable,
            str(package_dir / "secret_handoff_worker.py"),
            "--handoff-id",
            handoff_id,
            "--key-path",
            str(key_path),
        ],
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
        while time.time() < deadline:
            state = client.get_json(
                computer_api_path(platform_auth, f"private-secret-handoffs/v1/{handoff_id}")
            )
            status = str(state.get("status") or "").strip()
            if status == "submitted":
                _install_submitted_secret(
                    client=client,
                    platform_auth=platform_auth,
                    handoff_id=handoff_id,
                    private_key_pem=private_key_pem,
                    state=state,
                )
                return
            if status in {"claimed", "expired", "failed"}:
                return
            time.sleep(poll_after)
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


def _install_submitted_secret(
    *,
    client: PlatformClient,
    platform_auth: str,
    handoff_id: str,
    private_key_pem: str,
    state: dict[str, Any],
) -> None:
    if state.get("handoff_kind") == "slack_connection":
        from .slack_connection import install_submitted_slack_connection

        install_submitted_slack_connection(
            client=client,
            platform_auth=platform_auth,
            handoff_id=handoff_id,
            private_key_pem=private_key_pem,
            state=state,
        )
        return
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
    plaintext = _decrypt_ciphertext(private_key_pem, ciphertext_payload)
    try:
        _set_hermes_secret(secret_name, plaintext)
    finally:
        plaintext = ""
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
    for candidate in _hermes_script_candidates(Path(hermes)):
        for name in ("python", "python3"):
            python = candidate.parent / name
            if python.exists():
                return str(python)
        shebang = _read_first_line(candidate)
        if not shebang.startswith("#!"):
            continue
        try:
            parts = shlex.split(shebang[2:].strip())
        except ValueError:
            continue
        if not parts:
            continue
        executable = Path(parts[0])
        if executable.name.startswith("python") and executable.exists():
            return str(executable)
        if executable.name == "env" and len(parts) > 1 and parts[1].startswith("python"):
            python = shutil.which(parts[1])
            if python:
                return python
    return None


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
