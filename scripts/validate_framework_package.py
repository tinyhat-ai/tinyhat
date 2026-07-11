#!/usr/bin/env python3
"""Validate the fresh Hermes-only Tinyhat plugin package shape."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

VERSION_SHAPE = re.compile(r"^\d+\.\d+\.\d+$")
CODEX_SCREENSHOT_MIN_BYTES = 10_000
REQUIRED_TOOLS = [
    "tinyhat_plugin_version",
    "tinyhat_tell_joke",
    "tinyhat_skill_catalog",
    "tinyhat_private_secret_handoff",
    "tinyhat_google_workspace",
    "tinyhat_google_workspace_app",
    "tinyhat_google_workspace_app_manager",
    "tinyhat_codex_auth",
    "tinyhat_plugin_update",
]
REQUIRED_COMMANDS = [
    "tinyhat-joke",
    "tinyhat-plugin-version",
    "tinyhat-secret",
]
REQUIRED_SKILLS = [
    "tinyhat-plugin-version",
    "tinyhat-tell-joke",
    "tinyhat-skill-catalog",
    "tinyhat-private-secret",
    "tinyhat-google-workspace",
    "tinyhat-google-workspace-app-manager",
    "tinyhat-codex-auth",
    "tinyhat-plugin-update",
    "tinyhat-platform",
]
FORBIDDEN_PATHS = (
    "openclaw.plugin.json",
    "src",
    ".claude",
    "roadmap",
)
FORBIDDEN_TEXT = ("CLAUDE_PLUGIN_DATA",)


def fail(message: str) -> None:
    print(f"framework-package: {message}", file=sys.stderr)
    raise SystemExit(1)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"could not read {path.relative_to(repo_root())}: {exc}")
    except json.JSONDecodeError as exc:
        fail(f"{path.relative_to(repo_root())} is invalid JSON: {exc}")
    require(isinstance(value, dict), f"{path.relative_to(repo_root())} must be an object")
    return value


def read_pyproject_version(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, flags=re.MULTILINE)
    require(match is not None, "pyproject.toml must define project.version")
    return match.group(1)


def read_plugin_yaml(root: Path) -> dict[str, object]:
    text = (root / "plugin.yaml").read_text(encoding="utf-8")
    data: dict[str, object] = {}
    current_list: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_list:
            items = data.setdefault(current_list, [])
            require(isinstance(items, list), f"plugin.yaml {current_list} must be a list")
            items.append(stripped[2:].strip())
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            current_list = key if not value.strip() else None
            data[key] = [] if current_list else value.strip()
    return data


def validate_versions(root: Path) -> str:
    package = read_json(root / "package.json")
    hermes = read_json(root / "hermes.plugin.json")
    yaml_data = read_plugin_yaml(root)
    require(
        yaml_data.get("kind") == "standalone",
        "plugin.yaml kind must be standalone for Hermes",
    )
    version = package.get("version")
    require(isinstance(version, str), "package.json version must be a string")
    require(VERSION_SHAPE.fullmatch(version) is not None, "version must be shaped X.Y.Z")
    for label, found in (
        ("hermes.plugin.json version", hermes.get("version")),
        ("plugin.yaml version", yaml_data.get("version")),
        ("pyproject.toml project.version", read_pyproject_version(root)),
    ):
        require(found == version, f"{label} must match package.json version {version}")
    return version


def validate_hermes_adapter(root: Path) -> None:
    hermes = read_json(root / "hermes.plugin.json")
    yaml_data = read_plugin_yaml(root)
    require(hermes.get("schema") == "tinyhat.framework-adapter.v1", "adapter schema drift")
    framework = hermes.get("framework")
    require(isinstance(framework, dict), "framework must be an object")
    require(framework.get("name") == "hermes", "framework.name must be hermes")

    for rel in (
        "plugin.yaml",
        "hermes.plugin.json",
        "__init__.py",
        "schemas.py",
        "tools.py",
        "platform.py",
        "google_workspace.py",
        "google_workspace_app.py",
        "google_workspace_app_manager.py",
        "google_workspace_disconnect_worker.py",
        "google_workspace_worker.py",
        "secret_handoff.py",
        "secret_handoff_worker.py",
    ):
        require((root / rel).is_file(), f"{rel} is missing")

    codex_screenshot = (
        root
        / "skills"
        / "tinyhat-codex-auth"
        / "assets"
        / "chatgpt-enable-device-code-for-codex.png"
    )
    require(codex_screenshot.is_file(), "Codex auth prerequisite screenshot is missing")
    require(
        codex_screenshot.stat().st_size > CODEX_SCREENSHOT_MIN_BYTES,
        "Codex auth screenshot looks empty",
    )

    entrypoint = hermes.get("entrypoint")
    require(isinstance(entrypoint, dict), "entrypoint must be an object")
    require(entrypoint.get("manifest") == "plugin.yaml", "entrypoint.manifest must be plugin.yaml")
    require(entrypoint.get("module") == "__init__.py", "entrypoint.module must be __init__.py")
    require(entrypoint.get("register") == "register", "entrypoint.register must be register")

    provided_tools = yaml_data.get("provides_tools")
    require(isinstance(provided_tools, list), "plugin.yaml provides_tools must be a list")
    require(
        provided_tools == REQUIRED_TOOLS,
        "plugin.yaml provided tools drift",
    )

    source = (root / "__init__.py").read_text(encoding="utf-8")
    for phrase in ("ctx.register_tool", "ctx.register_skill", "ctx.register_command"):
        require(phrase in source, f"__init__.py missing {phrase}")

    skills = hermes.get("skills")
    require(isinstance(skills, list), "hermes.plugin.json skills must be a list")
    skill_names = [skill.get("name") for skill in skills if isinstance(skill, dict)]
    require(skill_names == REQUIRED_SKILLS, "skill declaration drift")
    expected_skill_paths = {
        "tinyhat-plugin-version": "skills/tinyhat-plugin-version/SKILL.md",
        "tinyhat-tell-joke": "skills/tinyhat-tell-joke/SKILL.md",
        "tinyhat-skill-catalog": "skills/tinyhat-skill-catalog/SKILL.md",
        "tinyhat-private-secret": "skills/tinyhat-private-secret/SKILL.md",
        "tinyhat-google-workspace": "skills/tinyhat-google-workspace/SKILL.md",
        "tinyhat-google-workspace-app-manager": (
            "skills/tinyhat-google-workspace-app-manager/SKILL.md"
        ),
        "tinyhat-codex-auth": "skills/tinyhat-codex-auth/SKILL.md",
        "tinyhat-plugin-update": "skills/tinyhat-plugin-update/SKILL.md",
        "tinyhat-platform": "skills/tinyhat-platform/SKILL.md",
    }
    for skill in skills:
        require(isinstance(skill, dict), "skill declaration must be an object")
        name = skill.get("name")
        require(
            skill.get("path") == expected_skill_paths.get(str(name)),
            f"{name} path drift",
        )
        require(
            (root / str(skill.get("path"))).is_file(),
            f"{name} proof skill missing",
        )
        require(
            skill.get("qualified_name") == f"tinyhat:{name}",
            f"{name} qualified_name drift",
        )
        aliases = skill.get("aliases")
        require(isinstance(aliases, list), f"{name} aliases must be a list")
        require(name in aliases, f"{name} aliases must include the unqualified name")

    tools = hermes.get("tools")
    require(isinstance(tools, list), "hermes.plugin.json tools must be a list")
    tool_names = [tool.get("name") for tool in tools if isinstance(tool, dict)]
    require(tool_names == REQUIRED_TOOLS, "tool declaration drift")

    commands = hermes.get("commands")
    require(isinstance(commands, list), "hermes.plugin.json commands must be a list")
    command_names = [command.get("name") for command in commands if isinstance(command, dict)]
    require(command_names == REQUIRED_COMMANDS, "command declaration drift")


def validate_fresh_surface(root: Path) -> None:
    for rel in FORBIDDEN_PATHS:
        require(not (root / rel).exists(), f"{rel} must not exist in this fresh Hermes branch")

    skill_dirs = sorted(path.name for path in (root / "skills").iterdir() if path.is_dir())
    require(
        skill_dirs == sorted(REQUIRED_SKILLS),
        "skills directory does not match the Tinyhat public capability set",
    )

    checked_roots = [
        root / "README.md",
        root / "AGENTS.md",
        root / "CONTRIBUTING.md",
        root / "RELEASING.md",
        root / "docs",
        root / ".agents",
        root / "skills",
        root / "test",
        root / "plugin.yaml",
        root / "hermes.plugin.json",
        root / "__init__.py",
        root / "platform.py",
        root / "context.py",
        root / "google_workspace.py",
        root / "google_workspace_app.py",
        root / "google_workspace_app_manager.py",
        root / "google_workspace_disconnect_worker.py",
        root / "google_workspace_worker.py",
        root / "secret_handoff.py",
        root / "secret_handoff_worker.py",
        root / "schemas.py",
        root / "tools.py",
    ]
    for base in checked_roots:
        files = [base] if base.is_file() else list(base.rglob("*"))
        for path in files:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for phrase in FORBIDDEN_TEXT:
                require(
                    phrase not in text,
                    f"{path.relative_to(root)} still references forbidden phrase {phrase!r}",
                )


def validate_docs(root: Path) -> None:
    checks = {
        "README.md": (
            "teaches an agent what the Tinyhat",
            "Hermes only",
            "tinyhat-tell-joke",
            "tinyhat-plugin-version",
            "tinyhat-skill-catalog",
            "tinyhat-private-secret",
            "tinyhat-google-workspace",
            "tinyhat_google_workspace_app",
            "tinyhat_google_workspace_app_manager",
            "tinyhat-codex-auth",
            "tinyhat-plugin-update",
            "tinyhat-platform",
            "pre_llm_call",
            "channels/lts",
            "channels/latest",
        ),
        "docs/skill-authoring.md": (
            "Tinyhat skills are public instructions",
            "Do not ask the user to paste secret values in chat.",
            "Secret Naming Standard",
            "Tinyhat Platform Context",
            "tinyhat-codex-auth",
            "tinyhat-skill-catalog",
            "tinyhat_google_workspace_app",
            "tinyhat_google_workspace_app_manager",
            "tinyhat-plugin-update",
        ),
        "skills/tinyhat-platform/SKILL.md": (
            "tinyhat_skill_catalog",
            "tinyhat_plugin_update",
            "tinyhat_google_workspace_app",
            "tinyhat_google_workspace_app_manager",
            "gws auth",
            "Reporting Tinyhat Bugs",
        ),
        "docs/capabilities.md": (
            "tinyhat_skill_catalog",
            "tinyhat_plugin_update",
            "tinyhat_google_workspace",
            "tinyhat_google_workspace_app",
            "tinyhat_google_workspace_app_manager",
            "Plugin Update And Skill Discovery",
        ),
        "skills/tinyhat-google-workspace/SKILL.md": (
            "existing Google account",
            "Connect my Google Workspace",
            "google_workspace_readonly_v1",
            "read-only Gmail, Calendar, and Drive",
            "native Telegram inline button",
            "Never print, paste, repeat",
            "does not revoke the shared Google",
            "tinyhat_google_workspace",
            "tinyhat_google_workspace_app",
            "Hermes's bundled `google-workspace` skill",
            "Never claim that only Gmail is exposed",
            "Never ask for a Google Cloud",
            "gws auth",
            "any second OAuth flow",
            '{"action": "connect"}',
            '{"action": "status"}',
            '{"action": "disconnect"}',
            "never call",
            '"confirmed": true',
            "exactly one **Revoke this Computer\u2019s access**",
            "**Confirm revoke** and **Cancel**",
            "Do not change the runtime",
        ),
        "skills/tinyhat-google-workspace-app-manager/SKILL.md": (
            "tinyhat_google_workspace_app_manager",
            '"action": "install", "confirmed": true',
            "Linux x86_64 and aarch64",
            "never run `gws auth`",
            "root-only quarantine",
        ),
        "skills/tinyhat-codex-auth/SKILL.md": (
            "For common natural-language requests, call `tinyhat_codex_auth` once",
            '{"action": "prerequisite"}',
            "caption is the user-facing reply.",
            "Keep `/codex_auth` on its own line",
            "Open `chatgpt.com`",
            "Secure sign in with ChatGPT",
            "Enable device code authorization for Codex",
            "Then come back here and tap:",
            "/codex_auth",
            "Do not call `tinyhat_codex_auth` twice",
            "Do not send an extra normal chat reply",
            '{"action": "start", "confirmed": true}',
            "tinyhat_codex_auth",
            "hermes_runtime.telegram_codex_auth start",
        ),
        ".agents/skills/tinyhat-plugin-skill-authoring/SKILL.md": (
            "Create, modify, or review Tinyhat plugin skills.",
            "Reject or clarify generic names",
        ),
        "RELEASING.md": (
            "channels/lts",
            "channels/latest",
            "codex/v0.20-hermes-plugin",
        ),
    }
    for rel, phrases in checks.items():
        text = (root / rel).read_text(encoding="utf-8")
        for phrase in phrases:
            require(phrase in text, f"{rel} missing phrase: {phrase}")


def validate_google_workspace_contract(root: Path) -> None:
    text = (root / "google_workspace.py").read_text(encoding="utf-8")
    required = (
        'GOOGLE_READONLY_CAPABILITY_BUNDLE = "google_workspace_readonly_v1"',
        'GOOGLE_GMAIL_SEND_CAPABILITY_BUNDLE = "google_workspace_gmail_send_v1"',
        'GOOGLE_WORKSPACE_PROFILE_GMAIL_SEND = "gmail_send"',
        'GOOGLE_REQUESTED_SERVICES = ("identity", "gmail", "calendar", "drive")',
        '"https://www.googleapis.com/auth/gmail.readonly"',
        '"https://www.googleapis.com/auth/calendar.readonly"',
        '"https://www.googleapis.com/auth/drive.readonly"',
        '"https://www.googleapis.com/auth/gmail.send"',
        '"requested_services": list(requested_profile.services)',
        '"requested_scopes": list(requested_profile.scopes)',
        '"button_sent": True',
        "_send_google_connect_button(authorization_url)",
        "_start_disconnect_intent()",
        "_start_disconnect_worker_process(",
        'f"{GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX}/{intent.intent_id}/activate"',
        'f"{GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX}/{intent.intent_id}/poll"',
        'f"{GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX}/{intent.intent_id}/claim"',
        'f"{GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX}/{intent.intent_id}/complete"',
        "GOOGLE_WORKSPACE_DISCONNECT_COMPLETION_RECEIPT_SCHEMA",
        "_write_disconnect_completion_receipt(",
        "_load_disconnect_completion_receipt(",
        "_resume_delete_pending_receipt(",
        "_retry_disconnect_completion(",
        "_sweep_expired_receiptless_disconnect_state(",
        "_resume_retained_disconnect_workers()",
        "record_completion_receipt=record_completion_receipt",
        "_wipe_invalid_credentials_and_pending_handoffs_locked()",
    )
    for phrase in required:
        require(phrase in text, f"google_workspace.py missing contract: {phrase}")
    forbidden = (
        '"authorization_url": authorization_url',
        "GOOGLE_REVOCATION_URI",
        "def _revoke_google_token",
        "def _disconnect_payload",
    )
    for phrase in forbidden:
        require(phrase not in text, f"google_workspace.py retained forbidden contract: {phrase}")

    app_text = (root / "google_workspace_app.py").read_text(encoding="utf-8")
    for phrase in (
        'APP_NAME = "gws"',
        "load_verified_google_workspace_credentials",
        "refresh_verified_google_workspace_credentials",
        '"GOOGLE_WORKSPACE_CLI_TOKEN": access_token',
        "ALLOWED_ROOT_COMMANDS",
        "verified_managed_gws_binary",
        "pass_fds=",
        "start_new_session=True",
        '"--page-all"',
        '"--output"',
        '"--upload"',
        '"--attach"',
        '"--draft"',
        '"--sanitize"',
        '"content_is_untrusted": True',
    ):
        require(phrase in app_text, f"google_workspace_app.py missing contract: {phrase}")
    for phrase in (
        "oauth2.googleapis.com/token",
        "shutil.which",
        "shell=True",
        'Path.home() / ".local"',
    ):
        require(
            phrase.lower() not in app_text.lower(),
            f"google_workspace_app.py retained forbidden contract: {phrase}",
        )

    manager_text = (root / "google_workspace_app_manager.py").read_text(encoding="utf-8")
    for phrase in (
        'PINNED_GWS_VERSION = "0.22.5"',
        '"de78ecdbd2f1a84cca0063a7ecbc440240fc14b6ebccbb17f4646b792a8c5c1f"',
        '"ab59c4bab4e7848740ba8cc3ef186152dab90121c45835b49bd1bf2a5c259b86"',
        '"94490295d9580e1e88574e715a0a162991747d12d62f8c7b8dcc8268b6c1cea0"',
        '"b68337faf1436fb2b3a287207cd57fef784a20fb4ab4f2429e51c4e0cfa0b50b"',
        '"9679052ece7c05ff3f05fb5f00c0437b460fade67631b60f279e445f5b5fd63e"',
        'BINARY_PATH = INSTALL_ROOT / "bin" / "gws"',
        "verified_managed_gws_binary",
        "tarfile.open",
        "_HttpsOnlyRedirectHandler",
        "_transactional_install",
        "managed_app_lock",
        "_sealed_executable_copy",
        "_recover_interrupted_install",
        "partially_uninstalled",
    ):
        require(phrase in manager_text, f"google_workspace_app_manager.py missing: {phrase}")
    for phrase in ("subprocess", "shell=True", "npm install", "curl "):
        require(
            phrase not in manager_text,
            f"google_workspace_app_manager.py retained forbidden contract: {phrase}",
        )


def main() -> int:
    root = repo_root()
    version = validate_versions(root)
    validate_hermes_adapter(root)
    validate_fresh_surface(root)
    validate_docs(root)
    validate_google_workspace_contract(root)
    print(f"framework-package: ok (version {version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
