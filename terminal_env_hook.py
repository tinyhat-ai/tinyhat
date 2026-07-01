"""Tinyhat-managed Hermes terminal env hook."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

HOOK_RELATIVE_PATH = ("tinyhat", "terminal-env.sh")


def _hermes_home() -> Path:
    explicit = (os.getenv("HERMES_HOME") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".hermes"


def _config_file() -> Path:
    explicit = (os.getenv("HERMES_CONFIG_FILE") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return _hermes_home() / "config.yaml"


def _hook_path() -> Path:
    return _hermes_home().joinpath(*HOOK_RELATIVE_PATH)


def _hook_script() -> str:
    return "\n".join(
        [
            "# Tinyhat-managed: export Hermes env files into terminal snapshots.",
            "__tinyhat_source_env_file() {",
            '  [ -r "$1" ] || return 0',
            '  case "$-" in *a*) __tinyhat_had_allexport=1 ;; *) __tinyhat_had_allexport=0 ;; esac',
            "  set -a",
            '  . "$1"',
            '  [ "$__tinyhat_had_allexport" = "1" ] || set +a',
            "}",
            '__tinyhat_source_env_file "${HERMES_ENV_FILE:-$HOME/.hermes/.env}"',
            '__tinyhat_source_env_file "${HERMES_PROJECT_DIR:-/usr/local/lib/hermes-agent}/.env"',
            "unset -f __tinyhat_source_env_file 2>/dev/null || true",
            "unset __tinyhat_had_allexport 2>/dev/null || true",
            "",
        ]
    )


def _is_top_level(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not line.startswith((" ", "\t")) and not stripped.startswith("#")


def _terminal_block_bounds(lines: list[str]) -> tuple[int, int] | None:
    start = None
    for index, line in enumerate(lines):
        if _is_top_level(line) and line.strip() == "terminal:":
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if _is_top_level(lines[index]):
            end = index
            break
    return start, end


def _inline_list_items(raw: str) -> list[str] | None:
    value = raw.strip()
    if value in {"", "[]", "null", "None"}:
        return []
    if not (value.startswith("[") and value.endswith("]")):
        return None
    return [
        item.strip().strip("'\"")
        for item in value[1:-1].split(",")
        if item.strip().strip("'\"")
    ]


def _ensure_shell_init_file(text: str, hook_path: str) -> tuple[str, bool]:
    lines = text.splitlines()
    if any(line.strip() == f"- {hook_path}" for line in lines):
        return text if text.endswith("\n") or not text else text + "\n", False

    bounds = _terminal_block_bounds(lines)
    if bounds is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["terminal:", "  shell_init_files:", f"    - {hook_path}"])
        return "\n".join(lines).rstrip() + "\n", True

    start, end = bounds
    shell_index = None
    for index in range(start + 1, end):
        if lines[index].strip().startswith("shell_init_files:"):
            shell_index = index
            break
    if shell_index is None:
        lines[start + 1:start + 1] = ["  shell_init_files:", f"    - {hook_path}"]
        return "\n".join(lines).rstrip() + "\n", True

    prefix, _sep, raw_value = lines[shell_index].partition(":")
    inline_items = _inline_list_items(raw_value)
    if inline_items is not None:
        block = [f"{prefix}:"]
        block.extend(f"    - {item}" for item in inline_items if item != hook_path)
        block.append(f"    - {hook_path}")
        lines[shell_index:shell_index + 1] = block
        return "\n".join(lines).rstrip() + "\n", True

    insert_at = shell_index + 1
    while insert_at < end and (
        lines[insert_at].startswith("    ") or not lines[insert_at].strip()
    ):
        insert_at += 1
    lines.insert(insert_at, f"    - {hook_path}")
    return "\n".join(lines).rstrip() + "\n", True


def install_terminal_env_reload_hook() -> dict[str, Any]:
    hook_path = _hook_path()
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    desired = _hook_script()
    hook_updated = (
        not hook_path.exists() or hook_path.read_text(encoding="utf-8") != desired
    )
    if hook_updated:
        hook_path.write_text(desired, encoding="utf-8")
    try:
        hook_path.chmod(0o600)
    except OSError:
        pass

    config_file = _config_file()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    before = config_file.read_text(encoding="utf-8") if config_file.exists() else ""
    after, config_updated = _ensure_shell_init_file(before, str(hook_path))
    if config_updated or not config_file.exists():
        config_file.write_text(after, encoding="utf-8")
    return {
        "installed": True,
        "hook": {"path": str(hook_path), "updated": hook_updated},
        "config": {"path": str(config_file), "updated": config_updated},
    }
