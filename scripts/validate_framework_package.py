#!/usr/bin/env python3
"""Validate the fresh Hermes-only Tinyhat plugin package shape."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


VERSION_SHAPE = re.compile(r"^\d+\.\d+\.\d+$")
REQUIRED_TOOL = "tinyhat_tell_joke"
REQUIRED_COMMAND = "tinyhat_joke"
REQUIRED_SKILL = "tinyhat-tell-joke"
FORBIDDEN_PATHS = (
    "openclaw.plugin.json",
    "src",
    ".agents",
    ".claude",
    "roadmap",
)
FORBIDDEN_TEXT = (
    "CLAUDE_PLUGIN_DATA",
    "ChatGPT subscription",
    "Mini App URL",
)


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

    for rel in ("plugin.yaml", "hermes.plugin.json", "__init__.py", "schemas.py", "tools.py"):
        require((root / rel).is_file(), f"{rel} is missing")

    entrypoint = hermes.get("entrypoint")
    require(isinstance(entrypoint, dict), "entrypoint must be an object")
    require(entrypoint.get("manifest") == "plugin.yaml", "entrypoint.manifest must be plugin.yaml")
    require(entrypoint.get("module") == "__init__.py", "entrypoint.module must be __init__.py")
    require(entrypoint.get("register") == "register", "entrypoint.register must be register")

    provided_tools = yaml_data.get("provides_tools")
    require(isinstance(provided_tools, list), "plugin.yaml provides_tools must be a list")
    require(provided_tools == [REQUIRED_TOOL], "plugin.yaml must provide only tinyhat_tell_joke")

    source = (root / "__init__.py").read_text(encoding="utf-8")
    for phrase in ("ctx.register_tool", "ctx.register_skill", "ctx.register_command"):
        require(phrase in source, f"__init__.py missing {phrase}")

    skills = hermes.get("skills")
    require(isinstance(skills, list), "hermes.plugin.json skills must be a list")
    require(len(skills) == 1, "this branch must ship exactly one skill")
    skill = skills[0]
    require(isinstance(skill, dict), "skill declaration must be an object")
    require(skill.get("name") == REQUIRED_SKILL, "only tinyhat-tell-joke is supported now")
    require(
        skill.get("path") == "skills/tinyhat-tell-joke/SKILL.md",
        "tinyhat-tell-joke path drift",
    )
    require((root / "skills" / REQUIRED_SKILL / "SKILL.md").is_file(), "proof skill missing")

    tools = hermes.get("tools")
    require(isinstance(tools, list), "hermes.plugin.json tools must be a list")
    require(len(tools) == 1 and tools[0].get("name") == REQUIRED_TOOL, "tool declaration drift")

    commands = hermes.get("commands")
    require(isinstance(commands, list), "hermes.plugin.json commands must be a list")
    require(
        len(commands) == 1 and commands[0].get("name") == REQUIRED_COMMAND,
        "command declaration drift",
    )


def validate_fresh_surface(root: Path) -> None:
    for rel in FORBIDDEN_PATHS:
        require(not (root / rel).exists(), f"{rel} must not exist in this fresh Hermes branch")

    skill_dirs = [path.name for path in (root / "skills").iterdir() if path.is_dir()]
    require(skill_dirs == [REQUIRED_SKILL], "only tinyhat-tell-joke may exist under skills/")

    checked_roots = [
        root / "README.md",
        root / "AGENTS.md",
        root / "CONTRIBUTING.md",
        root / "RELEASING.md",
        root / "docs",
        root / "skills",
        root / "test",
        root / "plugin.yaml",
        root / "hermes.plugin.json",
        root / "__init__.py",
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
            "channels/lts",
            "channels/latest",
        ),
        "docs/skill-authoring.md": (
            "Tinyhat skills are public instructions",
            "Do not ask the user to paste secret values in chat.",
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


def main() -> int:
    root = repo_root()
    version = validate_versions(root)
    validate_hermes_adapter(root)
    validate_fresh_surface(root)
    validate_docs(root)
    print(f"framework-package: ok (version {version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
