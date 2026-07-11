"""Bounded credential bridge from Tinyhat Google auth to the external gws app."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .google_workspace import (
    GOOGLE_TOKEN_VALUE_MAX_LENGTH,
    GoogleWorkspaceError,
    _assignment_binding_matches_platform,
    _cancel_all_pending_handoffs_locked,
    _delete_credentials_locked,
    _lifecycle_lock,
    _read_credentials,
    load_verified_google_workspace_credentials,
    refresh_verified_google_workspace_credentials,
)
from .platform import build_platform_client
from .tool_errors import tool_error_json

APP_NAME = "gws"
RESULT_SCHEMA = "tinyhat_google_workspace_app_v1"
MIN_ARG_COUNT = 1
MAX_ARG_COUNT = 64
MAX_ARG_BYTES = 4096
MAX_TOTAL_ARG_BYTES = 32 * 1024
APP_TIMEOUT_SECONDS = 30.0
MAX_STREAM_OUTPUT_BYTES = 64 * 1024
REFRESH_SKEW_SECONDS = 60
AUTH_FAILURE_EXIT_CODE = 2
PIPE_DRAIN_SECONDS = 0.2
KILLED_PIPE_DRAIN_SECONDS = 1.0
MIN_PRINTABLE_CODEPOINT = 0x20
DELETE_CODEPOINT = 0x7F
FORBIDDEN_ROOT_COMMANDS = {"auth", "setup", "login", "export", "mcp"}
ALLOWED_ROOT_COMMANDS = {"schema", "gmail", "calendar", "drive"}
ALLOWED_READ_HELPERS = {("calendar", "+agenda"), ("gmail", "+read")}
ALLOWED_WRITE_HELPERS = {("gmail", "+send")}
READ_METHOD_NAMES = {
    "download",
    "export",
    "get",
    "getprofile",
    "list",
    "query",
    "search",
}
FORBIDDEN_FLAGS = {
    "--attach",
    "--draft",
    "--output",
    "--page-all",
    "--sanitize",
    "--upload",
    "--upload-content-type",
}
UNSAFE_CODEPOINTS = {
    *range(0x00, 0x20),
    *range(0x7F, 0xA0),
    *range(0x200B, 0x2010),
    *range(0x2028, 0x202F),
    *range(0x2066, 0x206A),
    0xFEFF,
}
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
SECRET_FIELD_RE = re.compile(
    r"(?i)(\b(?:access_token|refresh_token|client_secret)\b\s*[=:]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,}]+)"
)
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


class GoogleWorkspaceAppError(RuntimeError):
    """A safe generic app-bridge failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.public_message = message
        super().__init__(code)


@dataclass(frozen=True)
class AppProcessResult:
    """Bounded result from one external app invocation."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    output_limited: bool = False


@dataclass(frozen=True)
class AppProcessLimits:
    """Internal fixed execution bounds, overridable only by focused tests."""

    timeout_seconds: float = APP_TIMEOUT_SECONDS
    output_limit_bytes: int = MAX_STREAM_OUTPUT_BYTES


@dataclass
class _CaptureState:
    buffers: dict[str, bytearray]
    seen: dict[str, int]
    deadline: float
    timed_out: bool = False
    output_limited: bool = False
    killed_at: float | None = None


@dataclass(frozen=True)
class _StreamLimits:
    capture_bytes: int
    output_bytes: int


def google_workspace_app(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Run one bounded gws command with the current Tinyhat Google credential."""
    payload = args if isinstance(args, dict) else {}
    if "argv" not in payload:
        return tool_error_json(
            tool="tinyhat_google_workspace_app",
            error_name="missing_required_parameter",
            message=(
                "Load the matching installed gws skill, then pass its bounded argv "
                "to tinyhat_google_workspace_app."
            ),
            missing=["argv"],
            expected={"argv": "array of 1..64 gws arguments"},
            example_call={"argv": ["schema", "service.resource.method"]},
        )
    try:
        argv = _normalize_argv(payload.get("argv"))
    except GoogleWorkspaceAppError as exc:
        return tool_error_json(
            tool="tinyhat_google_workspace_app",
            error_name=exc.code,
            message=exc.public_message,
            expected={"argv": "array of 1..64 bounded gws arguments"},
            example_call={"argv": ["schema", "service.resource.method"]},
        )

    effect = payload.get("effect")
    if effect not in {"read", "write"}:
        return tool_error_json(
            tool="tinyhat_google_workspace_app",
            error_name="invalid_parameter",
            message="Declare effect='read' or effect='write' for this gws invocation.",
            missing=["effect"],
            expected={"effect": ["read", "write"]},
            example_call={
                "argv": ["schema", "service.resource.method"],
                "effect": "read",
            },
        )
    if _argv_requires_write_effect(argv) and effect != "write":
        return tool_error_json(
            tool="tinyhat_google_workspace_app",
            error_name="write_effect_required",
            message=(
                "This gws command may change Google data. Mark it effect='write', "
                "then obtain separate confirmation for the exact operation."
            ),
            expected={"effect": "write"},
            example_call={"argv": argv, "effect": "write"},
        )
    if effect == "write":
        confirmation_id = _argv_confirmation_id(argv)
        if (
            payload.get("confirmed") is not True
            or payload.get("confirmation_id") != confirmation_id
        ):
            return tool_error_json(
                tool="tinyhat_google_workspace_app",
                error_name="confirmation_required",
                message=(
                    "Show or describe the exact recipients/content/effect and ask the "
                    "user to confirm this external write. Permission-upgrade approval "
                    "does not count. After confirmation, repeat the unchanged argv, "
                    "confirmed=true, and this confirmation_id."
                ),
                expected={"confirmation_id": confirmation_id},
                example_call={
                    "argv": argv,
                    "effect": "write",
                    "confirmed": True,
                    "confirmation_id": confirmation_id,
                },
            )

    try:
        result = run_google_workspace_app(argv=argv, effect=effect)
    except GoogleWorkspaceAppError as exc:
        result = {
            "schema": RESULT_SCHEMA,
            "status": "failed",
            "app": APP_NAME,
            "error": exc.code,
            "message": exc.public_message,
            "content_is_untrusted": True,
        }
    except Exception:
        result = {
            "schema": RESULT_SCHEMA,
            "status": "failed",
            "app": APP_NAME,
            "error": "unavailable",
            "message": "The Google Workspace app bridge could not run safely.",
            "content_is_untrusted": True,
        }
    return json.dumps(result, sort_keys=True)


def _normalize_argv(value: Any) -> list[str]:  # noqa: PLR0912
    if not isinstance(value, list):
        raise GoogleWorkspaceAppError("invalid_parameter", "argv must be an array of strings.")
    if not MIN_ARG_COUNT <= len(value) <= MAX_ARG_COUNT:
        raise GoogleWorkspaceAppError(
            "invalid_parameter", "argv must contain from 1 to 64 arguments."
        )

    normalized: list[str] = []
    total_bytes = 0
    for item in value:
        if not isinstance(item, str) or not item:
            raise GoogleWorkspaceAppError(
                "invalid_parameter", "Every argv item must be a non-empty string."
            )
        if any(ord(character) in UNSAFE_CODEPOINTS for character in item):
            raise GoogleWorkspaceAppError(
                "invalid_parameter",
                "argv cannot contain control or invisible formatting characters.",
            )
        encoded_length = len(item.encode("utf-8"))
        if encoded_length > MAX_ARG_BYTES:
            raise GoogleWorkspaceAppError(
                "invalid_parameter", "Each argv item must be 4096 bytes or fewer."
            )
        total_bytes += encoded_length
        if total_bytes > MAX_TOTAL_ARG_BYTES:
            raise GoogleWorkspaceAppError(
                "invalid_parameter", "The complete argv must be 32768 bytes or fewer."
            )
        normalized.append(item)

    root_command = normalized[0].lower()
    if root_command.startswith("-") or root_command == "gws":
        raise GoogleWorkspaceAppError(
            "blocked_command",
            "argv must start with the gws command namespace supplied by the installed skill.",
        )
    if root_command in FORBIDDEN_ROOT_COMMANDS:
        raise GoogleWorkspaceAppError(
            "blocked_command",
            "Authentication, setup, export, and persistent-server commands are not allowed here. "
            "Use Tinyhat Google connection instead of a second OAuth flow.",
        )
    if root_command not in ALLOWED_ROOT_COMMANDS:
        raise GoogleWorkspaceAppError(
            "blocked_command",
            "Only pinned Gmail, Calendar, Drive, and schema operation namespaces are allowed.",
        )
    if len(normalized) > 1 and normalized[1].startswith("+"):
        helper = (root_command, normalized[1].lower())
        if helper not in ALLOWED_READ_HELPERS | ALLOWED_WRITE_HELPERS:
            raise GoogleWorkspaceAppError(
                "blocked_command",
                "This gws helper is not part of Tinyhat's reviewed operation set.",
            )
    if any(_is_forbidden_flag(argument) for argument in normalized):
        raise GoogleWorkspaceAppError(
            "blocked_command",
            "File I/O, external sanitization, and unbounded pagination flags are not "
            "allowed through this bridge.",
        )
    return normalized


def _argv_requires_write_effect(argv: list[str]) -> bool:
    root = argv[0].lower()
    if root == "schema":
        return False
    if len(argv) > 1:
        helper = (root, argv[1].lower())
        if helper in ALLOWED_READ_HELPERS:
            return False
        if helper in ALLOWED_WRITE_HELPERS:
            return True
    positional: list[str] = []
    for argument in argv[1:]:
        if argument.startswith("-"):
            break
        positional.append(argument.lower())
    if not positional:
        return True
    # Discovery API calls end in their method name before flags. Fail closed:
    # only the reviewed read verbs may use effect=read; every unknown method is
    # treated as a write even if the CLI adds new mutators later.
    return positional[-1] not in READ_METHOD_NAMES


def _argv_confirmation_id(argv: list[str]) -> str:
    canonical = json.dumps(argv, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _is_forbidden_flag(argument: str) -> bool:
    lowered = argument.lower()
    if lowered == "-a" or lowered.startswith("-a="):
        return True
    if lowered.startswith("-a") and not lowered.startswith("--"):
        return True
    if lowered == "-o" or lowered.startswith("-o="):
        return True
    if lowered.startswith("-o") and not lowered.startswith("--"):
        return True
    return any(lowered == flag or lowered.startswith(f"{flag}=") for flag in FORBIDDEN_FLAGS)


def run_google_workspace_app(*, argv: list[str], effect: str = "read") -> dict[str, Any]:
    """Execute opaque gws argv without learning any Google service semantics."""
    with _open_trusted_gws_binary() as binary:
        try:
            credentials = load_verified_google_workspace_credentials()
        except GoogleWorkspaceError as exc:
            raise GoogleWorkspaceAppError(
                "not_connected",
                "Connect Google Workspace through Tinyhat on this Computer before using gws.",
            ) from exc

        refreshed = False
        if _access_token_needs_refresh(credentials):
            credentials = _refresh_credentials()
            refreshed = True

        process_result = _invoke_with_assignment_guard(
            binary=binary.proc_path,
            binary_fd=binary.fd,
            argv=argv,
            credentials=credentials,
        )
        if (
            process_result.returncode == AUTH_FAILURE_EXIT_CODE
            and not process_result.timed_out
            and not process_result.output_limited
            and not refreshed
        ):
            credentials = _refresh_credentials()
            refreshed = True
            process_result = _invoke_with_assignment_guard(
                binary=binary.proc_path,
                binary_fd=binary.fd,
                argv=argv,
                credentials=credentials,
            )

        return _result_payload(process_result, refreshed=refreshed, effect=effect)


def _refresh_credentials() -> dict[str, Any]:
    try:
        return refresh_verified_google_workspace_credentials()
    except GoogleWorkspaceError as exc:
        raise GoogleWorkspaceAppError(
            "refresh_failed",
            "Google authorization could not be refreshed safely through Tinyhat.",
        ) from exc


def _access_token_needs_refresh(
    credentials: dict[str, Any], *, now: datetime | None = None
) -> bool:
    value = str(credentials.get("expires_at") or "").strip()
    try:
        expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        return True
    current = now or datetime.now(timezone.utc)
    return expires_at <= current + timedelta(seconds=REFRESH_SKEW_SECONDS)


@contextlib.contextmanager
def _open_trusted_gws_binary():
    """Hold the manager's verified executable fd and shared lock through execution."""
    try:
        from .google_workspace_app_manager import (  # noqa: PLC0415
            GoogleWorkspaceAppManagerError,
            verified_managed_gws_binary,
        )
        with verified_managed_gws_binary() as binary:
            yield binary
            return
    except GoogleWorkspaceAppManagerError as exc:
        raise GoogleWorkspaceAppError(
            "app_unavailable",
            "The managed gws app is unavailable or failed integrity checks. Ask before "
            "using Tinyhat's Google Workspace app manager to install it.",
        ) from exc


def _invoke_with_assignment_guard(
    *,
    binary: str,
    binary_fd: int,
    argv: list[str],
    credentials: dict[str, Any],
) -> AppProcessResult:
    """Serialize local lifecycle changes and discard output after reassignment."""
    with _lifecycle_lock():
        current = _read_credentials()
        if current is None or not _same_credential_generation(current, credentials):
            raise GoogleWorkspaceAppError(
                "connection_changed",
                "The Google Workspace connection changed before the app could run.",
            )
        try:
            client, platform_auth = build_platform_client()
            if not _assignment_binding_matches_platform(
                credentials=current,
                client=client,
                platform_auth=platform_auth,
            ):
                _cancel_all_pending_handoffs_locked()
                _delete_credentials_locked()
                raise GoogleWorkspaceAppError(
                    "assignment_changed",
                    "The Computer assignment changed before the Google operation.",
                )
            result = _invoke_gws(
                binary=binary,
                binary_fd=binary_fd,
                argv=argv,
                credentials=current,
            )
            if not _assignment_binding_matches_platform(
                credentials=current,
                client=client,
                platform_auth=platform_auth,
            ):
                _cancel_all_pending_handoffs_locked()
                _delete_credentials_locked()
                raise GoogleWorkspaceAppError(
                    "assignment_changed",
                    "The Computer assignment changed during the Google operation; "
                    "its output was discarded.",
                )
            return result
        except GoogleWorkspaceAppError:
            raise
        except Exception as exc:
            raise GoogleWorkspaceAppError(
                "assignment_verification_failed",
                "The Computer could not verify assignment around the Google operation; "
                "its output was discarded.",
            ) from exc


def _same_credential_generation(
    current: dict[str, Any], expected: dict[str, Any]
) -> bool:
    for field in (
        "client_id",
        "access_token",
        "refresh_token",
        "tinyhat_assignment_binding",
        "capability_bundle",
    ):
        if not hmac.compare_digest(str(current.get(field) or ""), str(expected.get(field) or "")):
            return False
    return current.get("services") == expected.get("services") and current.get(
        "scopes"
    ) == expected.get("scopes")


def _invoke_gws(
    *,
    binary: str,
    binary_fd: int | None = None,
    argv: list[str],
    credentials: dict[str, Any],
) -> AppProcessResult:
    access_token = str(credentials.get("access_token") or "")
    refresh_token = str(credentials.get("refresh_token") or "")
    if not access_token or len(access_token) > GOOGLE_TOKEN_VALUE_MAX_LENGTH:
        raise GoogleWorkspaceAppError(
            "invalid_credentials", "The saved Google access credential is invalid."
        )
    return _run_bounded_process(
        binary=binary,
        binary_fd=binary_fd,
        argv=argv,
        access_token=access_token,
        secrets_to_redact=(access_token, refresh_token),
    )


def _run_bounded_process(  # noqa: PLR0913
    *,
    binary: str,
    binary_fd: int | None = None,
    argv: list[str],
    access_token: str,
    secrets_to_redact: tuple[str, ...],
    limits: AppProcessLimits | None = None,
) -> AppProcessResult:
    """Run gws with isolated child state and streaming output limits."""
    process_limits = limits or AppProcessLimits()
    output_limit_bytes = max(1, process_limits.output_limit_bytes)
    token_overlap = min(len(access_token.encode("utf-8")), GOOGLE_TOKEN_VALUE_MAX_LENGTH)
    capture_limit = output_limit_bytes + token_overlap

    with tempfile.TemporaryDirectory(prefix="tinyhat-gws-") as temporary_home:
        temporary_path = Path(temporary_home)
        config_path = temporary_path / "config"
        config_path.mkdir(mode=0o700)
        process = _spawn_isolated_gws(
            binary=binary,
            binary_fd=binary_fd,
            argv=argv,
            access_token=access_token,
            temporary_home=temporary_home,
            config_path=config_path,
        )
        captured = _capture_process(
            process=process,
            stream_limits=_StreamLimits(
                capture_bytes=capture_limit,
                output_bytes=output_limit_bytes,
            ),
            timeout_seconds=process_limits.timeout_seconds,
        )
        if captured.timed_out or captured.output_limited:
            return AppProcessResult(
                returncode=process.returncode,
                stdout="",
                stderr="",
                timed_out=captured.timed_out,
                output_limited=captured.output_limited,
            )
        stdout = _sanitize_output(
            bytes(captured.buffers["stdout"]),
            secrets=secrets_to_redact,
            paths=(temporary_home,),
            output_limit_bytes=output_limit_bytes,
        )
        stderr = _sanitize_output(
            bytes(captured.buffers["stderr"]),
            secrets=secrets_to_redact,
            paths=(temporary_home,),
            output_limit_bytes=output_limit_bytes,
        )
        return AppProcessResult(returncode=process.returncode, stdout=stdout, stderr=stderr)


def _spawn_isolated_gws(  # noqa: PLR0913
    *,
    binary: str,
    binary_fd: int | None,
    argv: list[str],
    access_token: str,
    temporary_home: str,
    config_path: Path,
) -> subprocess.Popen[bytes]:
    child_env = {
        "GOOGLE_WORKSPACE_CLI_TOKEN": access_token,
        "GOOGLE_WORKSPACE_CLI_CONFIG_DIR": str(config_path),
        "HOME": temporary_home,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "TMPDIR": temporary_home,
    }
    try:
        process = subprocess.Popen(
            [binary, *argv],
            cwd=temporary_home,
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
            pass_fds=(() if binary_fd is None else (binary_fd,)),
        )
    except OSError as exc:
        raise GoogleWorkspaceAppError(
            "app_unavailable", "The managed gws app could not start."
        ) from exc
    finally:
        child_env["GOOGLE_WORKSPACE_CLI_TOKEN"] = ""
        child_env.clear()
    if process.stdout is None or process.stderr is None:
        _kill_process_group(process)
        raise GoogleWorkspaceAppError("app_unavailable", "gws output could not be captured.")
    return process


def _capture_process(
    *,
    process: subprocess.Popen[bytes],
    stream_limits: _StreamLimits,
    timeout_seconds: float,
) -> _CaptureState:
    if process.stdout is None or process.stderr is None:
        raise GoogleWorkspaceAppError("app_unavailable", "gws output could not be captured.")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    state = _CaptureState(
        buffers={"stdout": bytearray(), "stderr": bytearray()},
        seen={"stdout": 0, "stderr": 0},
        deadline=time.monotonic() + max(0.01, timeout_seconds),
    )
    try:
        while selector.get_map():
            _enforce_process_deadline(process=process, state=state)
            events = selector.select(timeout=0.05)
            for key, _mask in events:
                _read_process_stream(
                    process=process,
                    selector=selector,
                    key=key,
                    state=state,
                    stream_limits=stream_limits,
                )
            if _capture_is_complete(process=process, events=events, state=state):
                break
    finally:
        selector.close()
        with contextlib.suppress(Exception):
            process.stdout.close()
        with contextlib.suppress(Exception):
            process.stderr.close()
    _wait_for_process(process)
    return state


def _enforce_process_deadline(*, process: subprocess.Popen[bytes], state: _CaptureState) -> None:
    now = time.monotonic()
    if process.poll() is None and now >= state.deadline and state.killed_at is None:
        state.timed_out = True
        _kill_process_group(process)
        state.killed_at = now


def _read_process_stream(
    *,
    process: subprocess.Popen[bytes],
    selector: selectors.BaseSelector,
    key: selectors.SelectorKey,
    state: _CaptureState,
    stream_limits: _StreamLimits,
) -> None:
    stream_name = str(key.data)
    try:
        chunk = os.read(key.fileobj.fileno(), 8192)
    except OSError:
        chunk = b""
    if not chunk:
        with contextlib.suppress(Exception):
            selector.unregister(key.fileobj)
        with contextlib.suppress(Exception):
            key.fileobj.close()
        return
    state.seen[stream_name] += len(chunk)
    remaining = max(0, stream_limits.capture_bytes - len(state.buffers[stream_name]))
    if remaining:
        state.buffers[stream_name].extend(chunk[:remaining])
    if state.seen[stream_name] > stream_limits.output_bytes:
        state.output_limited = True
    if state.seen[stream_name] > stream_limits.capture_bytes and state.killed_at is None:
        _kill_process_group(process)
        state.killed_at = time.monotonic()


def _capture_is_complete(
    *,
    process: subprocess.Popen[bytes],
    events: list[tuple[selectors.SelectorKey, int]],
    state: _CaptureState,
) -> bool:
    now = time.monotonic()
    if state.killed_at is not None and now - state.killed_at > KILLED_PIPE_DRAIN_SECONDS:
        return True
    if process.poll() is None or events:
        return False
    if state.killed_at is None:
        state.killed_at = now
        return False
    if now - state.killed_at <= PIPE_DRAIN_SECONDS:
        return False
    _kill_process_group(process)
    return True


def _wait_for_process(process: subprocess.Popen[bytes]) -> None:
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        process.wait(timeout=1)


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
        return
    with contextlib.suppress(OSError):
        process.kill()


def _sanitize_output(
    raw: bytes,
    *,
    secrets: tuple[str, ...],
    paths: tuple[str, ...],
    output_limit_bytes: int,
) -> str:
    text = raw.decode("utf-8", errors="replace")
    for secret in sorted((value for value in secrets if value), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    for path in sorted((value for value in paths if value), key=len, reverse=True):
        text = text.replace(path, "[PRIVATE_PATH]")
    text = BEARER_RE.sub("Bearer [REDACTED]", text)
    text = SECRET_FIELD_RE.sub(r"\1[REDACTED]", text)
    text = ANSI_ESCAPE_RE.sub("", text)
    text = "".join(
        character
        if character in "\n\r\t"
        or (ord(character) >= MIN_PRINTABLE_CODEPOINT and ord(character) != DELETE_CODEPOINT)
        else "�"
        for character in text
    )
    return _truncate_utf8(text.strip(), output_limit_bytes)


def _truncate_utf8(value: str, limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    suffix = "…"
    prefix = encoded[: max(0, limit - len(suffix.encode("utf-8")))].decode("utf-8", errors="ignore")
    return prefix + suffix


def _result_payload(
    process: AppProcessResult,
    *,
    refreshed: bool,
    effect: str,
) -> dict[str, Any]:
    if process.timed_out:
        return {
            "schema": RESULT_SCHEMA,
            "status": "failed",
            "app": APP_NAME,
            "error": "timeout",
            "message": "gws exceeded the fixed execution timeout.",
            "refreshed": refreshed,
            "effect": effect,
            "content_is_untrusted": True,
        }
    if process.output_limited:
        return {
            "schema": RESULT_SCHEMA,
            "status": "failed",
            "app": APP_NAME,
            "error": "output_limit_exceeded",
            "message": "gws exceeded the fixed output limit.",
            "refreshed": refreshed,
            "effect": effect,
            "content_is_untrusted": True,
        }

    output: Any = None
    output_format = "empty"
    if process.stdout:
        try:
            output = json.loads(process.stdout)
            output_format = "json"
        except json.JSONDecodeError:
            output = process.stdout
            output_format = "text"
    status = "ok" if process.returncode == 0 else "failed"
    payload: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "status": status,
        "app": APP_NAME,
        "exit_code": process.returncode,
        "output": output,
        "output_format": output_format,
        "stderr": process.stderr,
        "refreshed": refreshed,
        "effect": effect,
        "content_is_untrusted": True,
    }
    if process.returncode == AUTH_FAILURE_EXIT_CODE:
        payload["error"] = "authorization_expired"
        payload["message"] = (
            "Google authorization is still unavailable after one Tinyhat refresh. "
            "Reconnect through Tinyhat; do not run gws auth."
        )
    elif process.returncode != 0:
        payload["error"] = "app_error"
        payload["message"] = "gws returned a bounded application error."
    return payload
