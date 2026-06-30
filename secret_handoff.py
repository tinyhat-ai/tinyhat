"""Private secret handoff tool implementation."""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .platform import PlatformClient, build_platform_client, computer_api_path

KEY_ALGORITHM = "RSA-OAEP-256"
DEFAULT_EXPIRES_IN_SECONDS = 300
SECRET_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,126}$")
STATE_DIR = Path.home() / ".tinyhat" / "private-secret-handoffs"
GATEWAY_RELOAD_LOG_NAME = "hermes-gateway.log"
GENERIC_SECRET_NAMES = {
    "TINYHAT_SECRET",
    "SECRET",
    "API_KEY",
    "TOKEN",
    "PASSWORD",
    "CREDENTIAL",
    "WEBHOOK_SECRET",
}
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
    payload = args or {}
    description = _clean_description(payload.get("description"))
    secret_name = _resolve_secret_name(payload.get("name"), description)
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
    except Exception as exc:
        try:
            key_path.unlink()
        except OSError:
            pass
        raise SecretHandoffError(
            "Could not start the local secret handoff worker.",
            public_message="I could not start the secure secret saver on this Computer.",
        ) from exc


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
    ciphertext_payload = state.get("ciphertext_payload")
    if not isinstance(ciphertext_payload, dict):
        raise SecretHandoffError("Platform did not return ciphertext.")
    secret_name = _normalize_secret_name(str(state.get("secret_name") or ""))
    plaintext = _decrypt_ciphertext(private_key_pem, ciphertext_payload)
    try:
        _set_hermes_secret(secret_name, plaintext)
    finally:
        plaintext = ""
    _reload_hermes_gateway_after_secret()
    _claim_handoff(client, platform_auth, handoff_id, installed=True)


def _claim_handoff(
    client: PlatformClient,
    platform_auth: str,
    handoff_id: str,
    *,
    installed: bool,
    message: str | None = None,
) -> None:
    client.post_json(
        computer_api_path(
            platform_auth,
            f"private-secret-handoffs/v1/{handoff_id}/claim",
        ),
        {"installed": installed, "message": message},
    )


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
        raise SecretHandoffError("Hermes CLI was not found.")
    result = subprocess.run(
        [hermes, "config", "set", secret_name, value],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if result.returncode != 0:
        raise SecretHandoffError(
            "Hermes config set failed.",
            public_message="Hermes could not save this secret.",
        )


def _reload_hermes_gateway_after_secret() -> dict[str, Any]:
    """Restart Hermes messaging so newly saved env values are live immediately."""
    hermes = shutil.which("hermes")
    if not hermes:
        raise SecretHandoffError(
            "Hermes CLI was not found while reloading the gateway.",
            public_message=(
                "Secret saved, but I could not reload Hermes. Send /restart "
                "before using it."
            ),
        )

    status_before = _run_gateway_command([hermes, "gateway", "status"], timeout=45)
    stop = _run_gateway_command([hermes, "gateway", "stop"], timeout=60)
    status_after_stop = _run_gateway_command(
        [hermes, "gateway", "status"],
        timeout=45,
    )
    start = _run_gateway_command([hermes, "gateway", "start"], timeout=180)
    status_after_start = _wait_for_healthy_gateway(
        hermes,
        timeout_seconds=12,
    )

    foreground = None
    stop_left_gateway_running = _gateway_status_is_healthy(status_after_stop)
    if stop_left_gateway_running or _gateway_needs_foreground_run(
        start=start,
        status=status_after_start,
    ):
        # Local/Docker gateways may keep a foreground `gateway run` process
        # alive even after `gateway stop`. In that case use Hermes' public
        # replace mode so the new process gets a fresh env.
        foreground = _start_gateway_foreground(hermes)
        status_after_start = _wait_for_healthy_gateway(
            hermes,
            timeout_seconds=15,
            log_path=Path(str(foreground.get("log_path"))),
            log_start_offset=int(foreground.get("log_start_offset") or 0),
        )

    foreground_log = (
        Path(str(foreground.get("log_path")))
        if isinstance(foreground, dict) and foreground.get("log_path")
        else None
    )
    foreground_log_offset = (
        int(foreground.get("log_start_offset") or 0)
        if isinstance(foreground, dict)
        else 0
    )
    adapter_failure = _gateway_log_has_adapter_failure(
        foreground_log,
        since_byte=foreground_log_offset,
    )
    healthy = _gateway_status_is_healthy(status_after_start) and not adapter_failure
    recovery_start = None
    recovery_status = None
    if not healthy:
        recovery_start = _run_gateway_command([hermes, "gateway", "start"], timeout=60)
        recovery_status = _wait_for_healthy_gateway(
            hermes,
            timeout_seconds=12,
            log_path=foreground_log,
            log_start_offset=foreground_log_offset,
        )
        adapter_failure = _gateway_log_has_adapter_failure(
            foreground_log,
            since_byte=foreground_log_offset,
        )
        healthy = _gateway_status_is_healthy(recovery_status) and not adapter_failure

    result = {
        "schema": "tinyhat_secret_hermes_reload_v1",
        "healthy": healthy,
        "adapter_ready": not adapter_failure,
        "status_before": _compact_gateway_process(status_before),
        "stop": _compact_gateway_process(stop),
        "status_after_stop": _compact_gateway_process(status_after_stop),
        "start": _compact_gateway_process(start),
        "foreground": foreground,
        "status_after": _compact_gateway_process(status_after_start),
        "recovery_start": _compact_gateway_process(recovery_start),
        "recovery_status": _compact_gateway_process(recovery_status),
    }
    if not healthy:
        raise SecretHandoffError(
            f"Hermes gateway reload failed: {result}",
            public_message=(
                "Secret saved, but I could not reload Hermes. Send /restart "
                "before using it."
            ),
        )
    return result


def _run_gateway_command(command: list[str], *, timeout: int) -> dict[str, Any]:
    started_at = time.monotonic()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        duration_ms = int((time.monotonic() - started_at) * 1000)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "timed_out": False,
            "duration_ms": duration_ms,
            "stdout": str(result.stdout or "")[:4000],
            "stderr": str(result.stderr or "")[:4000],
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else exc.stdout
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else exc.stderr
        return {
            "ok": False,
            "returncode": None,
            "timed_out": True,
            "duration_ms": duration_ms,
            "stdout": str(stdout or "")[:4000],
            "stderr": str(stderr or "")[:4000],
        }


def _compact_gateway_process(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    return {
        "ok": bool(result.get("ok")),
        "returncode": result.get("returncode"),
        "timed_out": bool(result.get("timed_out")),
        "duration_ms": result.get("duration_ms"),
        "stdout": str(result.get("stdout") or "")[:1000],
        "stderr": str(result.get("stderr") or "")[:1000],
    }


def _gateway_process_text(result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict):
        return ""
    return f"{result.get('stdout') or ''}\n{result.get('stderr') or ''}".lower()


def _gateway_status_is_healthy(status: dict[str, Any] | None) -> bool:
    if not isinstance(status, dict) or not status.get("ok"):
        return False
    text = _gateway_process_text(status)
    if "not running" in text or "gateway is not running" in text:
        return False
    return True


def _gateway_needs_foreground_run(
    *,
    start: dict[str, Any],
    status: dict[str, Any],
) -> bool:
    text = f"{_gateway_process_text(start)}\n{_gateway_process_text(status)}"
    if "not applicable inside a docker container" in text:
        return True
    if "run the gateway directly" in text:
        return True
    return not _gateway_status_is_healthy(status)


def _wait_for_healthy_gateway(
    hermes: str,
    *,
    timeout_seconds: float,
    log_path: Path | None = None,
    log_start_offset: int = 0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status = _run_gateway_command([hermes, "gateway", "status"], timeout=45)
    while time.monotonic() < deadline:
        if _gateway_status_is_healthy(last_status) and not _gateway_log_has_adapter_failure(
            log_path,
            since_byte=log_start_offset,
        ):
            return last_status
        time.sleep(1)
        last_status = _run_gateway_command([hermes, "gateway", "status"], timeout=45)
    return last_status


def _gateway_log_path() -> Path:
    state_dir = os.getenv("TINYHAT_RUNTIME_STATE_DIR")
    if state_dir:
        return Path(state_dir) / GATEWAY_RELOAD_LOG_NAME
    return Path.home() / ".tinyhat" / GATEWAY_RELOAD_LOG_NAME


def _gateway_log_has_adapter_failure(path: Path | None, *, since_byte: int = 0) -> bool:
    if path is None:
        return False
    try:
        with path.open("rb") as handle:
            if since_byte > 0:
                handle.seek(since_byte)
            text = handle.read().decode("utf-8", errors="replace")[-8000:].lower()
    except OSError:
        return False
    needles = (
        "platform 'telegram' requirements not met",
        "adapter creation failed",
        "no adapter available for telegram",
    )
    return any(needle in text for needle in needles)


def _start_gateway_foreground(hermes: str) -> dict[str, Any]:
    log_path = _gateway_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_start_offset = log_path.stat().st_size
    except OSError:
        log_start_offset = 0
    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            [
                hermes,
                "gateway",
                "run",
                "--replace",
                "--force",
                "--accept-hooks",
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
    time.sleep(2)
    returncode = process.poll()
    return {
        "mode": "foreground_detached",
        "pid": process.pid,
        "started": returncode is None,
        "returncode": returncode,
        "log_path": str(log_path),
        "log_start_offset": log_start_offset,
    }


def _run(command: list[str], *, text: bool = True) -> str | bytes:
    result = subprocess.run(
        command,
        capture_output=True,
        text=text,
        timeout=45,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
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
