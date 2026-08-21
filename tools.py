"""Small public Tinyhat plugin tools used by framework adapters."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from .capabilities.contact_details.tool import contact_details as handle_contact_details
from .capabilities.credit.tool import (
    allocate_openrouter_credit as handle_allocate_openrouter_credit,
)
from .capabilities.credit.tool import (
    credit_summary as handle_credit_summary,
)
from .capabilities.credit.tool import (
    model_budget as handle_model_budget,
)
from .capabilities.google_workspace.app import (
    google_workspace_app as handle_google_workspace_app,
)
from .capabilities.google_workspace.app_manager import (
    google_workspace_app_manager as handle_google_workspace_app_manager,
)
from .capabilities.google_workspace.connection import (
    google_workspace as handle_google_workspace,
)
from .capabilities.hats.tool import hats as handle_hats
from .capabilities.local_app_sharing.tool import (
    local_app_sharing as handle_local_app_sharing,
)
from .capabilities.mail.tool import tinyhat_mail as handle_mail
from .capabilities.secrets.credentials import credentials as handle_credentials
from .capabilities.secrets.handoff import start_private_secret_handoff
from .capabilities.slack.connection import (
    start_slack_connection,
    start_slack_disconnect,
)
from .platform import PlatformError, build_platform_client, computer_api_path
from .tool_errors import tool_error_json

CODEX_AUTH_SCREENSHOT = (
    Path(__file__).resolve().parent
    / "skills"
    / "tinyhat-codex-auth"
    / "assets"
    / "chatgpt-enable-device-code-for-codex.png"
)
CODEX_AUTH_CAPTION = (
    "To use your Codex subscription here:\n\n"
    "1. Open chatgpt.com > Settings > Security.\n"
    '2. Turn on "Enable device code authorization for Codex".\n\n'
    "Then come back here and tap:\n\n"
    "/codex_auth"
)
TELEGRAM_ENV_CANDIDATES = (
    Path.home() / ".hermes" / ".env",
    Path("/usr/local/lib/hermes-agent/.env"),
)
CODEX_AUTH_ACTIONS = ("prerequisite", "start", "status", "log", "limits")
PLUGIN_UPDATE_ACTIONS = ("status", "update")
RUNTIME_OUTPUT_LIMIT = 1200
RUNTIME_JSON_OUTPUT_LIMIT = 12000


def _plugin_manifest() -> dict[str, Any]:
    manifest_path = Path(__file__).resolve().parent / "hermes.plugin.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def plugin_version_payload() -> dict[str, str]:
    """Return the version of the Tinyhat plugin code currently loaded."""
    manifest = _plugin_manifest()
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


def get_platform_status(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Read safe platform context for this attested Tinyhat Computer."""
    _ = args
    try:
        client, platform_auth = build_platform_client()
        payload = client.get_json(
            computer_api_path(platform_auth, "platform-status"),
        )
    except PlatformError as exc:
        return tool_error_json(
            tool="tinyhat_get_platform_status",
            error_name="platform_status_unavailable",
            message=str(exc),
        )
    return json.dumps(payload, sort_keys=True)


def credit(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Read the authenticated owner's Tinyhat credit summary."""
    return handle_credit_summary(args, **kwargs)


def model_budget(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Read the assigned Agent's current AI model budget."""
    return handle_model_budget(args, **kwargs)


def openrouter_credit_allocate(
    args: dict[str, Any] | None = None,
    **kwargs: Any,
) -> str:
    """Add owner credit to the assigned Agent's AI model budget."""
    return handle_allocate_openrouter_credit(args, **kwargs)


def contact_details(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Return or assign the current Agent's managed phone and email."""
    return handle_contact_details(args, **kwargs)


def mail(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Use the current Agent's private Tinyhat mailbox."""
    return handle_mail(args, **kwargs)


def hats(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Create, list, or inspect owner-scoped shareable hats."""
    return handle_hats(args, **kwargs)


def local_app_sharing(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Create, list, or revoke short-lived local application shares."""
    return handle_local_app_sharing(args, **kwargs)


def skill_catalog_payload() -> dict[str, Any]:
    """Return Tinyhat plugin skill names in qualified and alias forms."""
    manifest = _plugin_manifest()
    version = str(manifest.get("version") or "unknown").strip() or "unknown"
    skills: list[dict[str, Any]] = []
    for entry in manifest.get("skills") or []:
        if not isinstance(entry, dict):
            continue
        raw_name = str(entry.get("name") or "").strip()
        if not raw_name:
            continue
        qualified_name = str(entry.get("qualified_name") or f"tinyhat:{raw_name}")
        aliases = entry.get("aliases")
        if not isinstance(aliases, list):
            aliases = [raw_name]
        alias_names = [str(alias).strip() for alias in aliases if str(alias).strip()]
        if raw_name not in alias_names:
            alias_names.insert(0, raw_name)
        skills.append(
            {
                "name": raw_name,
                "qualified_name": qualified_name,
                "aliases": alias_names,
                "path": entry.get("path"),
                "purpose": entry.get("purpose"),
            }
        )
    return {
        "schema": "tinyhat_skill_catalog_v1",
        "plugin": {"name": "tinyhat", "version": version},
        "skills": skills,
        "lookup_rule": (
            "Prefer qualified names like tinyhat:tinyhat-codex-auth. If an "
            "unqualified skill_view lookup fails, retry the matching "
            "qualified_name from this catalog."
        ),
    }


def skill_catalog(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Hermes tool handler for reporting Tinyhat skill discovery metadata."""
    _ = args
    return json.dumps(skill_catalog_payload(), sort_keys=True)


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


def slack_connect(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Start the Hermes-owned Slack connection onboarding."""

    return start_slack_connection(args, **kwargs)


def slack_disconnect(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Start the owner-confirmed Slack revocation and local bundle removal."""

    return start_slack_disconnect(args, **kwargs)


def credentials(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """List or start confirmed deletion of value-blind Computer credentials."""
    return handle_credentials(args, **kwargs)


def google_workspace(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Connect, inspect, change, or disconnect Google access on this Computer."""
    return handle_google_workspace(args, **kwargs)


def google_workspace_app(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Bridge assignment-verified Google access to the separately installed gws app."""
    return handle_google_workspace_app(args, **kwargs)


def google_workspace_app_manager(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """Manage the pinned gws app; Hermes supplies operation guidance."""
    return handle_google_workspace_app_manager(args, **kwargs)


def codex_auth(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Send the Codex prerequisite first; start auth after confirmation."""
    payload = args if isinstance(args, dict) else {}
    raw_action = payload.get("action")
    if not isinstance(raw_action, str) or not raw_action.strip():
        return tool_error_json(
            tool="tinyhat_codex_auth",
            error_name="missing_required_parameter",
            message=(
                "Call tinyhat_codex_auth with action='prerequisite' for "
                "initial ChatGPT/Codex subscription setup."
            ),
            missing=["action"],
            example_call={"action": "prerequisite"},
        )

    action = raw_action.strip().lower()
    if action not in CODEX_AUTH_ACTIONS:
        return tool_error_json(
            tool="tinyhat_codex_auth",
            error_name="invalid_parameter",
            message=(
                "Unsupported tinyhat_codex_auth action. Use one of: "
                + ", ".join(CODEX_AUTH_ACTIONS)
                + "."
            ),
            expected={"action": list(CODEX_AUTH_ACTIONS)},
            example_call={"action": "prerequisite"},
        )

    if action == "start":
        if payload.get("confirmed") is not True:
            return tool_error_json(
                tool="tinyhat_codex_auth",
                error_name="confirmation_required",
                message=(
                    "Do not start auth yet. Ask the user to turn on Enable "
                    "device code authorization for Codex, then either tap "
                    "/codex_auth in Telegram or explicitly confirm the setting "
                    "is enabled."
                ),
                example_call={"action": "start", "confirmed": True},
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
    if action in {"status", "log", "limits"}:
        return _codex_auth_runtime_action(action)

    prerequisite = _send_codex_prerequisite()
    return json.dumps(
        {
            "schema": "tinyhat_codex_auth_start_v1",
            "status": "waiting_for_confirmation",
            "chat_response_required": False,
            "prerequisite": prerequisite,
            "next_user_action": (
                "After enabling the ChatGPT setting, the user taps /codex_auth " "in Telegram."
            ),
            "agent_instruction": (
                "The user-facing Telegram message has already been sent. Do not "
                "send any chat reply for this tool call. Do not call this tool "
                "again unless the user explicitly confirms the setting is enabled."
            ),
        },
        sort_keys=True,
    )


def plugin_update(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Check or apply the Tinyhat plugin update through runtime commands."""
    payload = args if isinstance(args, dict) else {}
    raw_action = payload.get("action")
    if not isinstance(raw_action, str) or not raw_action.strip():
        return tool_error_json(
            tool="tinyhat_plugin_update",
            error_name="missing_required_parameter",
            message="Call tinyhat_plugin_update with action='status' or action='update'.",
            missing=["action"],
            example_call={"action": "status"},
        )

    action = raw_action.strip().lower()
    if action not in PLUGIN_UPDATE_ACTIONS:
        return tool_error_json(
            tool="tinyhat_plugin_update",
            error_name="invalid_parameter",
            message=(
                "Unsupported tinyhat_plugin_update action. Use one of: "
                + ", ".join(PLUGIN_UPDATE_ACTIONS)
                + "."
            ),
            expected={"action": list(PLUGIN_UPDATE_ACTIONS)},
            example_call={"action": "status"},
        )

    if action == "status":
        result = _run_runtime_json_command("tinyhat_plugin_status")
        return json.dumps(
            {
                "schema": "tinyhat_plugin_update_action_v1",
                "action": "status",
                "status": "ok" if result["ok"] else "failed",
                "result": result,
                "next_action": (
                    "If update_available is true and the user/operator wants "
                    "the current channel applied, call tinyhat_plugin_update "
                    "with action=update, confirmed=true, and restart_gateway=true."
                ),
            },
            sort_keys=True,
        )

    if payload.get("confirmed") is not True:
        return tool_error_json(
            tool="tinyhat_plugin_update",
            error_name="confirmation_required",
            message=(
                "Do not update the Tinyhat plugin yet. Ask the user/operator "
                "to confirm applying the configured plugin channel to this Computer."
            ),
            example_call={
                "action": "update",
                "confirmed": True,
                "restart_gateway": True,
            },
        )

    update = _run_runtime_json_command("update_tinyhat_plugin", timeout_seconds=360)
    restart: dict[str, Any] = {"requested": False}
    if payload.get("restart_gateway") is True:
        restart = {
            "requested": True,
            "stop": _run_runtime_json_command("stop_hermes", timeout_seconds=120),
            "start": _run_runtime_json_command("start_hermes", timeout_seconds=240),
        }
    return json.dumps(
        {
            "schema": "tinyhat_plugin_update_action_v1",
            "action": "update",
            "status": "ok"
            if update["ok"]
            and (not restart["requested"] or (restart["stop"]["ok"] and restart["start"]["ok"]))
            else "failed",
            "update": update,
            "restart_gateway": restart,
            "message": (
                "Tinyhat plugin update path ran through the installed runtime. "
                "If restart_gateway was true, the Hermes gateway stop/start "
                "path was used so long-running agent commands can reload."
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
    return _run_runtime_command(script)


def _codex_auth_runtime_action(action: str) -> str:
    scripts = {
        "status": (
            'PYTHONPATH="${TINYHAT_RUNTIME_PREFIX:-/opt/tinyhat-hermes-runtime}:'
            '${PYTHONPATH:-}" python3 -m hermes_runtime.telegram_codex_auth status'
        ),
        "log": (
            'PYTHONPATH="${TINYHAT_RUNTIME_PREFIX:-/opt/tinyhat-hermes-runtime}:'
            '${PYTHONPATH:-}" python3 -m hermes_runtime.telegram_codex_auth log'
        ),
        "limits": (
            'PYTHONPATH="${TINYHAT_RUNTIME_PREFIX:-/opt/tinyhat-hermes-runtime}:'
            '${PYTHONPATH:-}" python3 -m hermes_runtime.codex_limits telegram'
        ),
    }
    script = scripts[action]
    result = _run_runtime_command(script)
    return json.dumps(
        {
            "schema": "tinyhat_codex_auth_action_v1",
            "action": action,
            "status": "ok" if result["ok"] else "failed",
            "result": result,
        },
        sort_keys=True,
    )


def _run_runtime_json_command(kind: str, *, timeout_seconds: int = 60) -> dict[str, Any]:
    command_json = json.dumps({"kind": kind, "spec": {}})
    script = (
        'PYTHONPATH="${TINYHAT_RUNTIME_PREFIX:-/opt/tinyhat-hermes-runtime}:'
        "${PYTHONPATH:-}\" python3 - <<'PY'\n"
        "import asyncio\n"
        "import json\n"
        "from types import SimpleNamespace\n"
        "from hermes_runtime.commands import run_command\n\n"
        "async def main():\n"
        f"    command = json.loads({command_json!r})\n"
        "    result = await run_command(SimpleNamespace(), command)\n"
        "    print(json.dumps(result, sort_keys=True))\n\n"
        "asyncio.run(main())\n"
        "PY"
    )
    process = _run_runtime_command(
        script,
        timeout_seconds=timeout_seconds,
        output_limit=RUNTIME_JSON_OUTPUT_LIMIT,
    )
    parsed: Any = None
    parse_error: str | None = None
    if process["ok"]:
        try:
            parsed = json.loads(process.get("stdout") or "{}")
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
    compact_process = dict(process)
    if parsed is not None:
        compact_process["stdout"] = ""
    return {
        "ok": bool(process["ok"] and parsed is not None),
        "command": kind,
        "result": parsed,
        "process": compact_process,
        "parse_error": parse_error,
    }


def _run_runtime_command(
    script: str,
    *,
    timeout_seconds: int = 15,
    output_limit: int = RUNTIME_OUTPUT_LIMIT,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["bash", "-lc", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": stdout[-output_limit:],
        "stderr": stderr[-output_limit:],
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
    if len(value) >= 2 and value[0] == value[-1] and value.startswith(("'", '"')):  # noqa: PLR2004
        value = value[1:-1]
    return value.replace('\\"', '"').replace("\\\\", "\\")


def _telegram_send_message(
    *,
    token: str,
    chat_id: str,
    text: str,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": "true",
    }
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(
            reply_markup,
            separators=(",", ":"),
        )
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
        ).encode()
        + photo
        + b"\r\n",
    ]
    parts.append(f"--{boundary}--\r\n".encode())
    return _telegram_post(
        token=token,
        method="sendPhoto",
        body=b"".join(parts),
        content_type=f"multipart/form-data; boundary={boundary}",
    )


def _multipart_field(boundary: str, name: str, value: str) -> bytes:
    return (
        f"--{boundary}\r\n" f'Content-Disposition: form-data; name="{name}"\r\n\r\n' f"{value}\r\n"
    ).encode()


def _telegram_post(*, token: str, method: str, body: bytes, content_type: str) -> dict[str, Any]:
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
