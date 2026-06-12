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
    "tinyhat_open_software_updates_link",
    "tinyhat_open_terminal_link",
    "tinyhat_report_problem",
    "tinyhat_secret_command",
}

REQUIRED_OPERATIONS = {
    "credentials.open_add_secret": "tinyhat_request_runtime_secret",
    "credentials.list_metadata": "tinyhat_list_runtime_secrets",
    "computer.open_manage": "tinyhat_open_manage_computer_link",
    "computer.software_updates": "tinyhat_open_software_updates_link",
    "computer.open_terminal": "tinyhat_open_terminal_link",
    "computer.status": "tinyhat_get_platform_status",
    "packages.list_installed": "tinyhat_list_installed_packages",
    "support.report_problem": "tinyhat_report_problem",
}

REQUIRED_SKILLS = {
    "tinyhat-platform",
    "tinyhat-secrets",
    "tinyhat-computer-access",
    "tinyhat-software-updates",
    "tinyhat-runtime-status",
    "tinyhat-package-inventory",
    "tinyhat-support-report",
}

VERSION_SHAPE = re.compile(r"^\d+(\.\d+)+$")

SKILL_MD_MAX_LINES = 200
SKILL_DESCRIPTION_MAX_CHARS = 1024
ALLOWED_SKILL_SUBDIRS = {"assets", "references", "scripts"}
TRIGGER_PHRASES = (
    "use when",
    "trigger when",
    "when the user",
    "when asked",
)
FORBIDDEN_SKILL_PATTERNS = {
    "raw URL": re.compile(r"https?://", re.IGNORECASE),
    "raw HAPI path": re.compile(r"/hapi/", re.IGNORECASE),
    "Mini App URL field": re.compile(r"\bmini_app_url\b", re.IGNORECASE),
    "signed URL field": re.compile(r"\bsigned_url\b", re.IGNORECASE),
    "private URL field": re.compile(r"\bprivate_url\b", re.IGNORECASE),
    "local user path": re.compile(r"/Users/|~/", re.IGNORECASE),
    "Google Drive path": re.compile(r"GoogleDrive|Shared drives", re.IGNORECASE),
}
SECRET_PASTE_REQUEST = re.compile(
    r"\b(ask|tell|have)\s+the\s+user\s+to\s+paste\b.*\b(secret|token|key)\b",
    re.IGNORECASE,
)
SECRET_PASTE_NEGATION = re.compile(
    r"\b(never|do not|don't|must not)\b.*\b(ask|tell|have)\b.*\buser\b.*\bpaste\b",
    re.IGNORECASE,
)

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


def parse_skill_frontmatter(
    display_path: Path,
    text: str,
) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        fail(f"{display_path} must start with frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        fail(f"{display_path} frontmatter must close with ---")
    raw = text[4:end]
    body = text[end + len("\n---\n") :]
    metadata: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            fail(f"{display_path} frontmatter line is not key: value: {line!r}")
        metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata, body


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

    declared_skills = contracts.get("skills")
    require(isinstance(declared_skills, list), "manifest contracts.skills must be a list")
    require(
        all(isinstance(name, str) and name for name in declared_skills),
        "manifest contracts.skills entries must be non-empty strings",
    )
    missing_skills = REQUIRED_SKILLS.difference(declared_skills)
    require(not missing_skills, f"manifest contracts.skills missing: {sorted(missing_skills)}")

    framework = contracts.get("framework")
    require(isinstance(framework, dict), "manifest contracts.framework must be an object")
    require(
        framework.get("name") == "openclaw",
        "manifest contracts.framework.name must be openclaw",
    )
    minimum = framework.get("minimum")
    require(
        isinstance(minimum, str) and VERSION_SHAPE.fullmatch(minimum) is not None,
        "manifest contracts.framework.minimum must be a dotted version string",
    )
    maximum = framework.get("maximum")
    require(
        maximum is None
        or (isinstance(maximum, str) and VERSION_SHAPE.fullmatch(maximum) is not None),
        "manifest contracts.framework.maximum must be a dotted version string when set",
    )

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


def validate_skills(root: Path, manifest: dict[str, Any]) -> None:
    skill_files = sorted((root / "skills").glob("*/SKILL.md"))
    require(skill_files, "skills/ must contain at least one SKILL.md")
    skill_names = {skill_file.parent.name for skill_file in skill_files}
    missing_skills = REQUIRED_SKILLS.difference(skill_names)
    require(not missing_skills, f"skills/ missing default skills: {sorted(missing_skills)}")
    # contracts.skills is the declared capability surface hosts verify
    # against; it must exactly match the tree this package ships.
    contracts = manifest.get("contracts")
    declared = set(contracts.get("skills") or []) if isinstance(contracts, dict) else set()
    undeclared = skill_names.difference(declared)
    require(
        not undeclared,
        f"skills/ ships skills the manifest does not declare: {sorted(undeclared)}",
    )
    phantom = declared.difference(skill_names)
    require(
        not phantom,
        f"manifest contracts.skills declares skills not in skills/: {sorted(phantom)}",
    )
    for skill_file in skill_files:
        text = skill_file.read_text(encoding="utf-8")
        relative_path = skill_file.relative_to(root)
        metadata, body = parse_skill_frontmatter(relative_path, text)
        name = metadata.get("name", "")
        description = metadata.get("description", "")
        require(
            re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is not None,
            f"{relative_path} frontmatter name must be lowercase kebab-case",
        )
        require(
            skill_file.parent.name == name,
            f"{relative_path} frontmatter name must match its directory",
        )
        require(description, f"{relative_path} is missing frontmatter description")
        require(
            len(description) <= SKILL_DESCRIPTION_MAX_CHARS,
            f"{relative_path} description must be <= {SKILL_DESCRIPTION_MAX_CHARS} characters",
        )
        description_lower = description.lower()
        require(
            any(phrase in description_lower for phrase in TRIGGER_PHRASES),
            f"{relative_path} description must say when to use or trigger the skill",
        )
        line_count = len(text.splitlines())
        require(
            line_count <= SKILL_MD_MAX_LINES,
            f"{relative_path} has {line_count} lines; limit is {SKILL_MD_MAX_LINES}",
        )
        require(
            "Never ask the user to paste a secret value in chat." in text,
            f"{relative_path} must include the secret-entry safety rule",
        )
        require(
            "raw Mini App URL" in text,
            f"{relative_path} must explicitly forbid raw Mini App URLs",
        )
        if name == "tinyhat-secrets":
            require(
                "Plain-English Name Inference" in text
                and "Do not require the user to know the exact env var name." in text,
                f"{relative_path} must teach agents to infer secret names from plain English",
            )

        for child in skill_file.parent.iterdir():
            if child.name == "SKILL.md":
                continue
            if child.is_dir() and child.name in ALLOWED_SKILL_SUBDIRS:
                continue
            fail(
                f"{child.relative_to(root)} is not allowed in a packaged skill directory; "
                f"use only SKILL.md or {sorted(ALLOWED_SKILL_SUBDIRS)}"
            )

        for label, pattern in FORBIDDEN_SKILL_PATTERNS.items():
            if pattern.search(body):
                fail(f"{relative_path} contains forbidden {label}")
        for line_number, line in enumerate(body.splitlines(), start=1):
            if SECRET_PASTE_REQUEST.search(line) and not SECRET_PASTE_NEGATION.search(line):
                fail(f"{relative_path}:{line_number} contains a forbidden secret paste request")


def validate_authoring_standard(root: Path) -> None:
    authoring = root / "docs" / "skill-authoring.md"
    require(authoring.is_file(), "docs/skill-authoring.md is missing")
    text = authoring.read_text(encoding="utf-8")
    required_phrases = (
        "trigger-led",
        "What Belongs Where",
        "Thin Harness, Focused Skills, Router Model",
        "Safety Rules",
        "Reviewer Checklist",
        "Good And Bad Examples",
    )
    for phrase in required_phrases:
        require(phrase in text, f"docs/skill-authoring.md must include {phrase!r}")

    for path in (root / "README.md", root / "CONTRIBUTING.md"):
        require(
            "docs/skill-authoring.md" in path.read_text(encoding="utf-8"),
            f"{path.name} must link to docs/skill-authoring.md",
        )


def validate_source(root: Path) -> None:
    source = (root / "src" / "index.js").read_text(encoding="utf-8")
    for tool_name in REQUIRED_TOOLS:
        require(f'name: "{tool_name}"' in source, f"src/index.js missing tool {tool_name}")
    for skill_name in REQUIRED_SKILLS:
        require(
            f'name: "{skill_name}"' in source, f"src/index.js missing default skill {skill_name}"
        )
    for command in (
        "tinyhat_secrets",
        "tinyhat_secrets_manage",
        "tinyhat_computer",
        "tinyhat_software",
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
    validate_authoring_standard(root)
    validate_skills(root, manifest)
    validate_source(root)
    validate_retired_terms_absent(root)

    print("openclaw-package: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
