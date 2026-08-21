"""Agent-facing tool for platform-owned local application sharing sessions."""

from __future__ import annotations

import fcntl
import json
import os
import re
import socket
import subprocess
import sys
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib import error, request

from ...platform import PlatformError, build_platform_client, computer_api_path
from ...tool_errors import tool_error_json

GATEWAY_HOST = "127.0.0.1"
GATEWAY_PORT = 9321
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
MAX_PORT = 65535
MAX_LABEL_LENGTH = 80
MIN_PRINTABLE_ORDINAL = 32
DEFAULT_TTL_SECONDS = 15 * 60
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 4 * 60 * 60
SESSION_ID_RE = re.compile(r"^las_[A-Za-z0-9_-]{20,80}$")
VIEWER_LINK_RE = re.compile(r"^https://viewd?\.tinyhat\.ai/s/las_[A-Za-z0-9_-]{20,80}$")
STATE_DIR = Path.home() / ".tinyhat" / "local-app-sharing"
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
    label = " ".join(str(value or "Local app").split())
    if (
        not label
        or len(label) > MAX_LABEL_LENGTH
        or any(ord(character) < MIN_PRINTABLE_ORDINAL for character in label)
    ):
        raise ValueError("label must be 1 to 80 printable characters")
    return label


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
        return response.status == HTTPStatus.OK and payload == {"ok": True}
    except (error.URLError, json.JSONDecodeError, OSError):
        return False


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


def _safe_created_payload(payload: dict[str, Any]) -> dict[str, Any]:
    required = {
        "session_id": str,
        "link": str,
        "access_code": str,
        "label": str,
        "port": int,
        "expires_at": str,
    }
    if any(not isinstance(payload.get(key), kind) for key, kind in required.items()):
        raise ValueError("platform returned an invalid sharing session")
    session_id = _clean_session_id(payload["session_id"])
    link = payload["link"].strip()
    if VIEWER_LINK_RE.fullmatch(link) is None or not link.endswith(session_id):
        raise ValueError("platform returned an invalid sharing link")
    access_code = payload["access_code"].strip()
    if re.fullmatch(r"[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}", access_code) is None:
        raise ValueError("platform returned an invalid access code")
    return {
        "schema": "tinyhat_local_app_share_v1",
        "status": "active",
        "session_id": session_id,
        "link": link,
        "access_code": access_code,
        "label": payload["label"],
        "port": payload["port"],
        "expires_at": payload["expires_at"],
        "message": "Share this link and access code with the user.",
    }


def _create(payload: dict[str, Any]) -> dict[str, Any]:
    port = _clean_port(payload.get("port"))
    if not _port_is_open(port):
        raise ValueError(f"no local application is listening on port {port}")
    label = _clean_label(payload.get("label"))
    ttl_seconds = _clean_ttl(payload.get("ttl_seconds"))
    ensure_gateway_running()
    client, platform_auth = build_platform_client()
    response = client.post_json(
        computer_api_path(platform_auth, "local-app-shares/v1"),
        {"port": port, "label": label, "ttl_seconds": ttl_seconds},
    )
    return _safe_created_payload(response)


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
        safe_sessions.append(
            {
                "session_id": session_id,
                "link": link,
                "label": str(raw.get("label") or "Local app")[:80],
                "port": _clean_port(raw.get("port")),
                "expires_at": str(raw.get("expires_at") or ""),
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
    return {
        "schema": "tinyhat_local_app_share_revoke_v1",
        "session_id": session_id,
        "status": "revoked",
    }


def local_app_sharing(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Create, list, or revoke platform-owned local application shares."""

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
            message="Tinyhat local app sharing is temporarily unavailable.",
        )
    return json.dumps(result, sort_keys=True)


__all__ = ["ensure_gateway_running", "local_app_sharing"]
