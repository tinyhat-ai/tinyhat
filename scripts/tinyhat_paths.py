#!/usr/bin/env python3
"""Resolve Tinyhat's writable home under Claude Code plugin data."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import TextIO

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
LEGACY_HOME_ROOT = Path.home() / ".claude" / "tinyhat"
PLUGIN_DATA_ROOT = Path.home() / ".claude" / "plugins" / "data"


def _sanitize_plugin_id(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return slug or "tinyhat"


def _fallback_plugin_id() -> str:
    manifest_path = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "tinyhat"

    name = data.get("name")
    if isinstance(name, str) and name.strip():
        return _sanitize_plugin_id(name)
    return "tinyhat"


def default_home_root() -> Path:
    raw = os.getenv("CLAUDE_PLUGIN_DATA")
    if raw:
        return Path(raw).expanduser()
    return PLUGIN_DATA_ROOT / _fallback_plugin_id()


def legacy_home_root() -> Path:
    return LEGACY_HOME_ROOT


def _conflict_target(target: Path) -> Path:
    candidate = target.with_name(f"{target.name}.legacy")
    idx = 2
    while candidate.exists():
        candidate = target.with_name(f"{target.name}.legacy-{idx}")
        idx += 1
    return candidate


def _merge_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        target = dst / entry.name
        if not target.exists():
            shutil.move(str(entry), str(target))
            continue
        if entry.is_dir() and target.is_dir():
            _merge_tree(entry, target)
            with contextlib.suppress(OSError):
                entry.rmdir()
            continue
        if entry.is_file() and target.is_file():
            try:
                if entry.read_bytes() == target.read_bytes():
                    entry.unlink()
                    continue
            except OSError:
                pass
        shutil.move(str(entry), str(_conflict_target(target)))


def migrate_legacy_home(new_root: Path, *, stderr: TextIO = sys.stderr) -> bool:
    legacy_root = LEGACY_HOME_ROOT
    if not legacy_root.exists() or legacy_root == new_root:
        return False

    new_root.parent.mkdir(parents=True, exist_ok=True)
    if not new_root.exists():
        shutil.move(str(legacy_root), str(new_root))
        print(f"migrated: {legacy_root} -> {new_root}", file=stderr)
        return True

    _merge_tree(legacy_root, new_root)
    with contextlib.suppress(OSError):
        legacy_root.rmdir()

    if legacy_root.exists():
        print(
            f"warn: legacy Tinyhat data still exists at {legacy_root}; new writes go to {new_root}.",
            file=stderr,
        )
    else:
        print(f"migrated: {legacy_root} -> {new_root}", file=stderr)
    return True


def resolve_home_root(home_root: str | Path | None, *, migrate_legacy: bool = True) -> Path:
    root = default_home_root() if home_root is None else Path(home_root).expanduser()
    if home_root is None and migrate_legacy:
        migrate_legacy_home(root)
    return root
