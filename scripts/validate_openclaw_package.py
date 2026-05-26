#!/usr/bin/env python3
"""Validate the public Tinyhat OpenClaw plugin package shape."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED_TOOLS = {
    "tinyhat_get_platform_status",
    "tinyhat_list_installed_packages",
    "tinyhat_list_runtime_secrets",
    "tinyhat_request_runtime_secret",
    "tinyhat_open_manage_computer_link",
    "tinyhat_open_terminal_link",
    "tinyhat_report_problem",
    "tinyhat_secret_command",
}

REQUIRED_OPERATIONS = {
    "credentials.open_add_secret": "tinyhat_request_runtime_secret",
    "credentials.list_metadata": "tinyhat_list_runtime_secrets",
    "computer.open_manage": "tinyhat_open_manage_computer_link",
    "computer.open_terminal": "tinyhat_open_terminal_link",
    "computer.status": "tinyhat_get_platform_status",
    "packages.list_installed": "tinyhat_list_installed_packages",
    "support.report_problem": "tinyhat_report_problem",
}

RETIRED_PUBLIC_TERMS = (
    "gather_snapshot",
    "render_report",
    "tinyhat-snapshot",
    "CLAUDE_PLUGIN_DATA",
    "skill-audit",
)

PUBLIC_TEXT_ROOTS = (
    "README.md",
    "docs",
    "skills",
    "src",
    "openclaw.plugin.json",
    "package.json",
)


def fail(message: str) -> None:
    print(f"openclaw-package: {message}", file=sys.stderr)
    raise SystemExit(1)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"could not read {path.name}: {exc}")
    except json.JSONDecodeError as exc:
        fail(f"{path.name} is invalid JSON: {exc}")
    if not isinstance(value, dict):
        fail(f"{path.name} must contain a JSON object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def validate_versions(root: Path, manifest: dict[str, Any], package: dict[str, Any]) -> None:
    require(manifest.get("id") == "tinyhat", "manifest id must be tinyhat")
    require(package.get("name") == "tinyhat", "package name must be tinyhat")
    manifest_version = manifest.get("version")
    package_version = package.get("version")
    require(isinstance(manifest_version, str), "manifest version must be a string")
    require(isinstance(package_version, str), "package version must be a string")
    require(manifest_version == package_version, "manifest and package versions must match")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    require(match is not None, "pyproject.toml must include project version")
    require(match.group(1) == package_version, "pyproject and package versions must match")


def validate_package_metadata(package: dict[str, Any]) -> None:
    files = package.get("files")
    require(isinstance(files, list), "package.json files must be a list")
    for expected in ("src", "skills", "docs", "openclaw.plugin.json", "README.md", "LICENSE"):
        require(expected in files, f"package.json files must include {expected}")

    openclaw = package.get("openclaw")
    require(isinstance(openclaw, dict), "package.json must include openclaw metadata")
    extensions = openclaw.get("extensions")
    require(
        isinstance(extensions, list) and "./src/index.js" in extensions,
        "package.json openclaw.extensions must include ./src/index.js",
    )


def validate_manifest(manifest: dict[str, Any]) -> None:
    require(manifest.get("skills") == ["skills"], "manifest skills must point at skills/")

    contracts = manifest.get("contracts")
    require(isinstance(contracts, dict), "manifest contracts must be an object")
    require(
        contracts.get("capabilityContract") == "tinyhat.openclaw.platform.v0.5",
        "manifest capabilityContract must be tinyhat.openclaw.platform.v0.5",
    )

    tools = contracts.get("tools")
    require(isinstance(tools, list), "manifest contracts.tools must be a list")
    missing_tools = REQUIRED_TOOLS.difference(tools)
    require(not missing_tools, f"manifest missing tools: {sorted(missing_tools)}")

    operations = contracts.get("operations")
    require(isinstance(operations, list), "manifest contracts.operations must be a list")
    operation_map = {
        item.get("name"): item.get("tool") for item in operations if isinstance(item, dict)
    }
    for operation, tool_name in REQUIRED_OPERATIONS.items():
        require(
            operation_map.get(operation) == tool_name,
            f"operation {operation} must map to {tool_name}",
        )
    for operation, tool_name in operation_map.items():
        require(tool_name in tools, f"operation {operation} references unknown tool {tool_name}")

    security = contracts.get("security")
    require(isinstance(security, dict), "manifest contracts.security must be an object")
    require(
        security.get("secretValues") == "never_returned_to_agent",
        "manifest must state that secret values are never returned",
    )
    require(
        security.get("miniAppUrls") == "telegram_web_app_buttons_only",
        "manifest must state that Mini App URLs are button-only",
    )


def validate_skills(root: Path) -> None:
    skill_files = sorted((root / "skills").glob("*/SKILL.md"))
    require(skill_files, "skills/ must contain at least one SKILL.md")
    for skill_file in skill_files:
        text = skill_file.read_text(encoding="utf-8")
        require(text.startswith("---\n"), f"{skill_file} must start with frontmatter")
        require(
            re.search(r"^name:\s*[A-Za-z0-9_-]+\s*$", text, re.MULTILINE) is not None,
            f"{skill_file} is missing frontmatter name",
        )
        require(
            re.search(r"^description:\s*\S", text, re.MULTILINE) is not None,
            f"{skill_file} is missing frontmatter description",
        )
        require(
            "Never ask the user to paste a secret value in chat." in text,
            f"{skill_file} must include the secret-entry safety rule",
        )


def validate_source(root: Path) -> None:
    source = (root / "src" / "index.js").read_text(encoding="utf-8")
    for tool_name in REQUIRED_TOOLS:
        require(f'name: "{tool_name}"' in source, f"src/index.js missing tool {tool_name}")
    for command in (
        "tinyhat_secrets",
        "tinyhat_secrets_manage",
        "tinyhat_computer",
        "tinyhat_terminal",
    ):
        require(f'name: "{command}"' in source, f"src/index.js missing command {command}")
    require(
        "Do not paste the value in chat." in source,
        "src/index.js must keep secret-entry replies out of chat",
    )


def iter_public_text_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for entry in PUBLIC_TEXT_ROOTS:
        path = root / entry
        if path.is_file():
            out.append(path)
        elif path.is_dir():
            out.extend(p for p in path.rglob("*") if p.is_file())
    return out


def validate_retired_terms_absent(root: Path) -> None:
    offenders: list[str] = []
    for path in iter_public_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for term in RETIRED_PUBLIC_TERMS:
            if term in text:
                offenders.append(f"{path.relative_to(root)}:{term}")
    require(not offenders, f"retired audit-plugin terms remain: {', '.join(offenders)}")


def main() -> int:
    root = repo_root()
    manifest = read_json(root / "openclaw.plugin.json")
    package = read_json(root / "package.json")

    validate_versions(root, manifest, package)
    validate_package_metadata(package)
    validate_manifest(manifest)
    validate_skills(root)
    validate_source(root)
    validate_retired_terms_absent(root)

    print("openclaw-package: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
