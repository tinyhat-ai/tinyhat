"""Small public Tinyhat plugin tools used by framework adapters."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any
from urllib import error, parse, request

from .secret_handoff import start_private_secret_handoff

CODEX_AUTH_SCREENSHOT = (
    Path(__file__).resolve().parent
    / "skills"
    / "tinyhat-codex-auth"
    / "assets"
    / "chatgpt-enable-device-code-for-codex.png"
)
CODEX_AUTH_CAPTION = (
    "Before Codex sign-in can start:\n\n"
    "1. Open chatgpt.com > Settings > Security.\n"
    '2. Turn on "Enable device code authorization for Codex".\n\n'
    "Then tap this command:\n"
    "/codex_auth"
)
TELEGRAM_ENV_CANDIDATES = (
    Path.home() / ".hermes" / ".env",
    Path("/usr/local/lib/hermes-agent/.env"),
)


def plugin_version_payload() -> dict[str, str]:
    """Return the version of the Tinyhat plugin code currently loaded."""
    manifest_path = Path(__file__).resolve().parent / "hermes.plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = str(manifest.get("version") or "unknown").strip() or "unknown"
    return {
        "schema": "tinyhat_plugin_version_v1",
        "name": "tinyhat",
        "version": version,
    }


def plugin_version(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Hermes tool handler for reporting the loaded Tinyhat plugin version."""
    _ = args
    return json.dumps(plugin_version_payload(), sort_keys=True)


def joke_text(topic: str | None = None) -> str:
    """Return the deterministic joke used to prove the plugin is wired."""
    subject = topic.strip() if isinstance(topic, str) and topic.strip() else "runtime"
    return (
        f"Why did the Tinyhat {subject} carry a notebook? "
        "Because transparent skills should leave readable notes."
    )


def tell_joke(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Hermes tool handler for the Tinyhat joke proof.

    Hermes can pass dispatcher metadata such as ``task_id`` to tool handlers.
    The Tinyhat plugin should ignore that metadata so the tool works from the
    first live agent interaction.
    """
    payload = args or {}
    return json.dumps(
        {
            "schema": "tinyhat_tell_joke_v1",
            "joke": joke_text(payload.get("topic")),
        },
        sort_keys=True,
    )


def private_secret_handoff(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Start a blind private-secret handoff through the Tinyhat platform."""
    return start_private_secret_handoff(args, **kwargs)


def codex_auth(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Send the Codex prerequisite first; start auth after confirmation."""
    payload = args or {}
    action = str(payload.get("action") or "prerequisite").strip().lower()
    if action in {"start", "link"}:
        if payload.get("confirmed") is not True:
            return json.dumps(
                {
                    "schema": "tinyhat_codex_auth_start_v1",
                    "status": "waiting_for_confirmation",
                    "message": (
                        "Do not start auth yet. Do not send another screenshot or "
                        "link. Ask the user to turn on Enable device code "
                        "authorization for Codex, then tap /codex_auth in the "
                        "Telegram message."
                    ),
                },
                sort_keys=True,
            )
        auth_start = _start_runtime_codex_auth()
        return json.dumps(
            {
                "schema": "tinyhat_codex_auth_start_v1",
                "status": "started" if auth_start["ok"] else "failed",
                "auth_start": auth_start,
                "message": (
                    "I started OpenAI Codex auth. Use the OpenAI button and "
                    "code from the Telegram messages."
                ),
            },
            sort_keys=True,
        )

    prerequisite = _send_codex_prerequisite()
    return json.dumps(
        {
            "schema": "tinyhat_codex_auth_start_v1",
            "status": "waiting_for_confirmation",
            "chat_response_required": False,
            "prerequisite": prerequisite,
            "next_user_action": (
                "After enabling the ChatGPT setting, the user taps /codex_auth "
                "in Telegram."
            ),
            "agent_instruction": (
                "The user-facing Telegram message has already been sent. Do not "
                "send any chat reply for this tool call. Do not call this tool "
                "again unless the user explicitly confirms the setting is enabled."
            ),
        },
        sort_keys=True,
    )


def _send_codex_prerequisite() -> dict[str, Any]:
    """Deliver the prerequisite image through Telegram when possible."""
    try:
        token, chat_id = _telegram_credentials()
    except RuntimeError as exc:
        return {"ok": False, "mode": "skipped", "error": str(exc)}
    if CODEX_AUTH_SCREENSHOT.is_file():
        sent = _telegram_send_photo(
            token=token,
            chat_id=chat_id,
            photo_path=CODEX_AUTH_SCREENSHOT,
            caption=CODEX_AUTH_CAPTION,
        )
        if sent.get("ok"):
            return {"ok": True, "mode": "photo"}
        fallback = _telegram_send_message(
            token=token,
            chat_id=chat_id,
            text=CODEX_AUTH_CAPTION,
        )
        return {
            "ok": bool(fallback.get("ok")),
            "mode": "text_fallback",
            "photo_error": _safe_telegram_error(sent),
        }
    sent = _telegram_send_message(
        token=token,
        chat_id=chat_id,
        text=CODEX_AUTH_CAPTION,
    )
    return {
        "ok": bool(sent.get("ok")),
        "mode": "text",
    }


def _start_runtime_codex_auth() -> dict[str, Any]:
    script = (
        'PYTHONPATH="${TINYHAT_RUNTIME_PREFIX:-/opt/tinyhat-hermes-runtime}:'
        '${PYTHONPATH:-}" python3 -m hermes_runtime.telegram_codex_auth start'
    )
    try:
        completed = subprocess.run(
            ["bash", "-lc", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": stdout[-1200:],
        "stderr": stderr[-1200:],
    }


def _telegram_credentials() -> tuple[str, str]:
    values = _telegram_env_values()
    token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = values.get("TELEGRAM_HOME_CHANNEL", "").strip()
    if not chat_id:
        allowed_users = values.get("TELEGRAM_ALLOWED_USERS", "").strip()
        if allowed_users and "," not in allowed_users:
            chat_id = allowed_users
    if not token or not chat_id:
        raise RuntimeError("Telegram is not configured for this Hermes instance yet.")
    return token, chat_id


def _telegram_env_values() -> dict[str, str]:
    values = {
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN") or "",
        "TELEGRAM_HOME_CHANNEL": os.getenv("TELEGRAM_HOME_CHANNEL") or "",
        "TELEGRAM_ALLOWED_USERS": os.getenv("TELEGRAM_ALLOWED_USERS") or "",
    }
    explicit = (os.getenv("HERMES_ENV_FILE") or "").strip()
    candidates = [Path(explicit).expanduser()] if explicit else []
    candidates.extend(TELEGRAM_ENV_CANDIDATES)
    for path in candidates:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            clean = line.strip()
            if not clean or clean.startswith("#") or "=" not in clean:
                continue
            key, raw_value = clean.split("=", 1)
            key = key.strip()
            if key in values and not values[key]:
                values[key] = _parse_env_value(raw_value)
    return values


def _parse_env_value(raw: str) -> str:
    value = raw.strip()
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value.startswith(("'", '"'))
    ):
        value = value[1:-1]
    return value.replace('\\"', '"').replace("\\\\", "\\")


def _telegram_send_message(
    *,
    token: str,
    chat_id: str,
    text: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": "true",
    }
    body = parse.urlencode(payload).encode("utf-8")
    return _telegram_post(
        token=token,
        method="sendMessage",
        body=body,
        content_type="application/x-www-form-urlencoded",
    )


def _telegram_send_photo(
    *,
    token: str,
    chat_id: str,
    photo_path: Path,
    caption: str,
) -> dict[str, Any]:
    boundary = "tinyhat_codex_auth_boundary"
    photo = photo_path.read_bytes()
    parts = [
        _multipart_field(boundary, "chat_id", chat_id),
        _multipart_field(boundary, "caption", caption[:1024]),
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="photo"; '
            f'filename="{photo_path.name}"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode("utf-8")
        + photo
        + b"\r\n",
    ]
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return _telegram_post(
        token=token,
        method="sendPhoto",
        body=b"".join(parts),
        content_type=f"multipart/form-data; boundary={boundary}",
    )


def _multipart_field(boundary: str, name: str, value: str) -> bytes:
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        f"{value}\r\n"
    ).encode("utf-8")


def _telegram_post(
    *, token: str, method: str, body: bytes, content_type: str
) -> dict[str, Any]:
    req = request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": content_type,
            "User-Agent": "tinyhat-plugin/telegram-codex-auth",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "http_status": exc.code, "description": detail[:500]}
    except error.URLError as exc:
        return {"ok": False, "description": str(exc.reason)[:500]}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "description": "Telegram returned invalid JSON."}
    return payload if isinstance(payload, dict) else {"ok": False}


def _safe_telegram_error(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in ("ok", "http_status", "error_code", "description")
        if key in payload
    }
