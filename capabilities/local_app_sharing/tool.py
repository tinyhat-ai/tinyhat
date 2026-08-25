"""Agent-facing tool for platform-owned Tinyhat Visuals."""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from contextlib import suppress
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib import error, request

from ...platform import PlatformError, build_platform_client, computer_api_path
from ...tool_errors import tool_error_json
from .connector import ensure_connector_running
from .crypto import (
    CONTENT_ENCRYPTION_PROTOCOL,
    LocalAppCryptoError,
    SessionKeyStore,
    encrypted_link,
)

GATEWAY_HOST = "127.0.0.1"
GATEWAY_PORT = 9321
GATEWAY_PROTOCOL_VERSION = 17
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
MAX_PORT = 65535
MAX_LABEL_LENGTH = 80
MAX_BUTTON_LABEL_LENGTH = 64
MIN_PRINTABLE_ORDINAL = 32
DEFAULT_TTL_SECONDS = 15 * 60
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 4 * 60 * 60
ACCESS_MODES = {"code", "link"}
ENCRYPTION_MODES = {
    "plain": "none",
    "encrypted": CONTENT_ENCRYPTION_PROTOCOL,
}
SESSION_ID_RE = re.compile(r"^las_[A-Za-z0-9_-]{20,80}$")
VIEWER_LINK_RE = re.compile(
    r"^https://c-[0-9a-f]{24}\.(?:viewd|view)\.tinyhat\.ai/"
    r"s/las_[A-Za-z0-9_-]{20,80}$",
    re.IGNORECASE,
)
STATE_DIR = Path.home() / ".tinyhat" / "local-app-sharing"
SESSION_KEY_STORE = SessionKeyStore(STATE_DIR / "sessions")
GATEWAY_PID_PATH = STATE_DIR / "gateway.pid"
GATEWAY_LOG_PATH = STATE_DIR / "gateway.log"
GATEWAY_LOCK_PATH = STATE_DIR / "gateway.lock"
GATEWAY_BOOTSTRAP = """\
import importlib.util
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location(
    "tinyhat",
    root / "__init__.py",
    submodule_search_locations=[str(root)],
)
if spec is None or spec.loader is None:
    raise RuntimeError("could not load Tinyhat plugin package")
package = importlib.util.module_from_spec(spec)
sys.modules["tinyhat"] = package
spec.loader.exec_module(package)
from tinyhat.capabilities.local_app_sharing.gateway import serve

serve()
"""


def _clean_label(value: Any) -> str:
    label = " ".join(str(value or "Visual").split())
    if (
        not label
        or len(label) > MAX_LABEL_LENGTH
        or any(ord(character) < MIN_PRINTABLE_ORDINAL for character in label)
    ):
        raise ValueError("label must be 1 to 80 printable characters")
    return label


def _clean_button_label(value: Any) -> str:
    button_label = " ".join(str(value or "Open visual").split())
    if (
        not button_label
        or len(button_label) > MAX_BUTTON_LABEL_LENGTH
        or any(ord(character) < MIN_PRINTABLE_ORDINAL for character in button_label)
    ):
        raise ValueError("button_label must be 1 to 64 printable characters")
    return button_label


def _clean_port(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PORT:
        raise ValueError("port must be an integer from 1 to 65535")
    if value == GATEWAY_PORT:
        raise ValueError("the sharing gateway port cannot be shared")
    return value


def _clean_ttl(value: Any) -> int:
    ttl = DEFAULT_TTL_SECONDS if value is None else value
    if (
        isinstance(ttl, bool)
        or not isinstance(ttl, int)
        or not MIN_TTL_SECONDS <= ttl <= MAX_TTL_SECONDS
    ):
        raise ValueError(f"ttl_seconds must be {MIN_TTL_SECONDS} to {MAX_TTL_SECONDS}")
    return ttl


def _clean_access_mode(value: Any) -> str:
    access_mode = str(value or "code").strip().lower()
    if access_mode not in ACCESS_MODES:
        raise ValueError("access_mode must be code or link")
    return access_mode


def _clean_encryption_mode(value: Any) -> str:
    encryption_mode = str(value or "plain").strip().lower()
    if encryption_mode not in ENCRYPTION_MODES:
        raise ValueError("encryption_mode must be plain or encrypted")
    return encryption_mode


def _clean_session_id(value: Any) -> str:
    session_id = str(value or "").strip()
    if SESSION_ID_RE.fullmatch(session_id) is None:
        raise ValueError("session_id is missing or invalid")
    return session_id


def _port_is_open(port: int) -> bool:
    try:
        with socket.create_connection((GATEWAY_HOST, port), timeout=0.5):
            return True
    except OSError:
        return False


def _gateway_is_healthy() -> bool:
    try:
        with request.urlopen(
            f"http://{GATEWAY_HOST}:{GATEWAY_PORT}/__tinyhat_share/health",
            timeout=0.5,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return response.status == HTTPStatus.OK and payload == {
            "ok": True,
            "protocol_version": GATEWAY_PROTOCOL_VERSION,
            "content_transports": ["none", CONTENT_ENCRYPTION_PROTOCOL],
        }
    except (error.URLError, json.JSONDecodeError, OSError):
        return False


def _stop_stale_gateway() -> None:
    """Stop only the plugin gateway recorded in the private PID file."""

    try:
        pid = int(GATEWAY_PID_PATH.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return
    if pid <= 1:
        return
    try:
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return
    if "local_app_sharing.gateway" not in command or str(PACKAGE_ROOT) not in command:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(20):
        if not _port_is_open(GATEWAY_PORT):
            return
        time.sleep(0.05)


def _prepare_state_dir() -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)


def _gateway_process_args() -> list[str]:
    """Return an install-location-independent gateway launch command."""

    return [sys.executable, "-c", GATEWAY_BOOTSTRAP, str(PACKAGE_ROOT)]


def ensure_gateway_running() -> None:
    """Start the plugin-owned loopback gateway when it is not already healthy."""

    if _gateway_is_healthy():
        return
    _prepare_state_dir()
    with GATEWAY_LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        os.chmod(GATEWAY_LOCK_PATH, 0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if _gateway_is_healthy():
            return
        _stop_stale_gateway()
        with GATEWAY_LOG_PATH.open("ab", buffering=0) as log_file:
            os.chmod(GATEWAY_LOG_PATH, 0o600)
            process = subprocess.Popen(
                _gateway_process_args(),
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        GATEWAY_PID_PATH.write_text(f"{process.pid}\n", encoding="ascii")
        os.chmod(GATEWAY_PID_PATH, 0o600)
        for _ in range(30):
            if process.poll() is not None:
                break
            if _gateway_is_healthy():
                return
            time.sleep(0.1)
    raise RuntimeError("the local sharing gateway did not become ready")


def _expires_at_epoch(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("platform returned an invalid sharing expiry") from exc
    epoch = parsed.timestamp()
    if epoch <= time.time():
        raise ValueError("platform returned an expired sharing session")
    return epoch


def _safe_created_payload(payload: dict[str, Any]) -> dict[str, Any]:
    required = {
        "session_id": str,
        "link": str,
        "access_mode": str,
        "label": str,
        "port": int,
        "expires_at": str,
    }
    if any(not isinstance(payload.get(key), kind) for key, kind in required.items()):
        raise ValueError("platform returned an invalid sharing session")
    content_encryption = str(payload.get("content_encryption") or "")
    if content_encryption not in ENCRYPTION_MODES.values():
        raise ValueError("platform returned an unsupported sharing transport")
    encryption_mode = (
        "encrypted" if content_encryption == CONTENT_ENCRYPTION_PROTOCOL else "plain"
    )
    session_id = _clean_session_id(payload["session_id"])
    link = payload["link"].strip()
    if VIEWER_LINK_RE.fullmatch(link) is None or not link.endswith(session_id):
        raise ValueError("platform returned an invalid sharing link")
    access_mode = _clean_access_mode(payload["access_mode"])
    access_code = payload.get("access_code")
    if access_mode == "code":
        if not isinstance(access_code, str) or re.fullmatch(r"[0-9]{4}", access_code) is None:
            raise ValueError("platform returned an invalid access code")
    elif access_code not in {None, ""}:
        raise ValueError("platform returned a code for a link-only share")
    safe = {
        "schema": "tinyhat_local_app_share_v1",
        "status": "active",
        "session_id": session_id,
        "link": link,
        "mini_app_url": link,
        "access_mode": access_mode,
        "label": payload["label"],
        "expires_at": payload["expires_at"],
        "encryption_mode": encryption_mode,
        "content_encryption": content_encryption,
        "message": (
            "The public Visual and Telegram button are ready."
            if access_mode == "link"
            else "The private Visual, Telegram button, and browser access code are ready."
        ),
    }
    if access_mode == "code":
        safe["access_code"] = access_code
    return safe


def _send_share_button(created: dict[str, Any]) -> bool:
    """Send the owner a native Mini App button with browser fallback details."""

    try:
        # Late import avoids a cycle through the root Hermes tool facade.
        from ...tools import _telegram_credentials, _telegram_send_message  # noqa: PLC0415

        token, chat_id = _telegram_credentials()
        access_detail = (
            "Access: Anyone with this complete link can open it.\n"
            if created["access_mode"] == "link"
            else f"Access code: {created['access_code']}\n"
        )
        sent = _telegram_send_message(
            token=token,
            chat_id=chat_id,
            text=(
                f"Your Visual, {created['label']}, is ready.\n\n"
                "Open the Visual inside Telegram with the button below, or use this link "
                "in any browser:\n"
                f"{created['link']}\n\n"
                f"{access_detail}"
                f"Available until: {created['expires_at']}"
            ),
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": _clean_button_label(created.get("button_label")),
                            "web_app": {"url": created["mini_app_url"]},
                        }
                    ]
                ]
            },
        )
        return bool(sent.get("ok"))
    except Exception:
        return False


def _create(payload: dict[str, Any]) -> dict[str, Any]:
    port = _clean_port(payload.get("port"))
    if not _port_is_open(port):
        raise ValueError("the page for this Visual is not available yet")
    label = _clean_label(payload.get("label"))
    button_label = _clean_button_label(payload.get("button_label"))
    ttl_seconds = _clean_ttl(payload.get("ttl_seconds"))
    access_mode = _clean_access_mode(payload.get("access_mode"))
    encryption_mode = _clean_encryption_mode(payload.get("encryption_mode"))
    content_encryption = ENCRYPTION_MODES[encryption_mode]
    ensure_gateway_running()
    client, platform_auth = build_platform_client()
    expected_origin = ensure_connector_running(
        client=client,
        platform_auth=platform_auth,
    )
    response = client.post_json(
        computer_api_path(platform_auth, "local-app-shares/v1"),
        {
            "port": port,
            "label": label,
            "ttl_seconds": ttl_seconds,
            "access_mode": access_mode,
            "content_encryption": content_encryption,
        },
    )
    created = _safe_created_payload(response)
    if not created["link"].startswith(f"{expected_origin}/s/"):
        raise ValueError("platform returned a sharing link for another Computer")
    if created["encryption_mode"] != encryption_mode:
        raise ValueError("platform returned a different sharing transport")
    if encryption_mode == "encrypted":
        try:
            session_key = SESSION_KEY_STORE.create(
                session_id=created["session_id"],
                expires_at_epoch=_expires_at_epoch(created["expires_at"]),
            )
            registration = client.post_json(
                computer_api_path(
                    platform_auth,
                    f"local-app-shares/v1/{created['session_id']}/link-fingerprint",
                ),
                {"fingerprint": session_key.fingerprint},
            )
            if (
                registration.get("session_id") != created["session_id"]
                or registration.get("status") != "registered"
            ):
                raise ValueError("platform returned an invalid Visual link registration")
        except (LocalAppCryptoError, PlatformError, OSError, ValueError) as exc:
            with suppress(PlatformError, OSError):
                client.delete_json(
                    computer_api_path(
                        platform_auth,
                        f"local-app-shares/v1/{created['session_id']}",
                    )
                )
            SESSION_KEY_STORE.delete(created["session_id"])
            raise RuntimeError(
                "the Computer could not create the encrypted sharing key"
            ) from exc
        created["link"] = encrypted_link(created["link"], session_key.fingerprint)
    created["mini_app_url"] = created["link"]
    created["button_label"] = button_label
    created["telegram_button_sent"] = _send_share_button(created)
    return created


def _list() -> dict[str, Any]:
    client, platform_auth = build_platform_client()
    response = client.get_json(
        computer_api_path(platform_auth, "local-app-shares/v1"),
    )
    sessions = response.get("sessions")
    if not isinstance(sessions, list):
        raise ValueError("platform returned an invalid sharing session list")
    safe_sessions: list[dict[str, Any]] = []
    for raw in sessions:
        if not isinstance(raw, dict):
            raise ValueError("platform returned an invalid sharing session list")
        session_id = _clean_session_id(raw.get("session_id"))
        link = str(raw.get("link") or "").strip()
        if VIEWER_LINK_RE.fullmatch(link) is None or not link.endswith(session_id):
            raise ValueError("platform returned an invalid sharing link")
        content_encryption = str(raw.get("content_encryption") or "")
        if content_encryption not in ENCRYPTION_MODES.values():
            raise ValueError("platform returned an unsupported sharing transport")
        encryption_mode = (
            "encrypted" if content_encryption == CONTENT_ENCRYPTION_PROTOCOL else "plain"
        )
        access_mode = _clean_access_mode(raw.get("access_mode"))
        _clean_port(raw.get("port"))
        if encryption_mode == "encrypted":
            try:
                session_key = SESSION_KEY_STORE.load(session_id)
            except LocalAppCryptoError as exc:
                raise ValueError(
                    "Computer encryption state is missing for an active share"
                ) from exc
            link = encrypted_link(link, session_key.fingerprint)
        safe_sessions.append(
            {
                "session_id": session_id,
                "link": link,
                "label": str(raw.get("label") or "Visual")[:80],
                "expires_at": str(raw.get("expires_at") or ""),
                "access_mode": access_mode,
                "encryption_mode": encryption_mode,
                "content_encryption": content_encryption,
            }
        )
    return {
        "schema": "tinyhat_local_app_share_list_v1",
        "sessions": safe_sessions,
    }


def _revoke(payload: dict[str, Any]) -> dict[str, Any]:
    session_id = _clean_session_id(payload.get("session_id"))
    client, platform_auth = build_platform_client()
    response = client.delete_json(
        computer_api_path(platform_auth, f"local-app-shares/v1/{session_id}"),
    )
    if response.get("status") != "revoked" or response.get("session_id") != session_id:
        raise ValueError("platform returned an invalid revocation response")
    SESSION_KEY_STORE.delete(session_id)
    return {
        "schema": "tinyhat_local_app_share_revoke_v1",
        "session_id": session_id,
        "status": "revoked",
    }


def local_app_sharing(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Create, list, or expire platform-owned Tinyhat Visuals."""

    payload = args if isinstance(args, dict) else {}
    action = str(payload.get("action") or "").strip().lower()
    if action not in {"create", "list", "revoke"}:
        return tool_error_json(
            tool="tinyhat_local_app_sharing",
            error_name="invalid_action",
            message="Use action=create, list, or revoke.",
        )
    try:
        result = (
            _create(payload)
            if action == "create"
            else _list()
            if action == "list"
            else _revoke(payload)
        )
    except ValueError as exc:
        return tool_error_json(
            tool="tinyhat_local_app_sharing",
            error_name="invalid_local_app_share_request",
            message=str(exc),
        )
    except (PlatformError, RuntimeError, OSError):
        return tool_error_json(
            tool="tinyhat_local_app_sharing",
            error_name="local_app_sharing_unavailable",
            message="Tinyhat Visuals are temporarily unavailable.",
        )
    return json.dumps(result, sort_keys=True)


__all__ = ["ensure_gateway_running", "local_app_sharing"]
