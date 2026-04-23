#!/usr/bin/env python3
"""Resolve Tinyhat's writable home under Claude Code plugin data.

Priority order for picking the home directory:

1. ``CLAUDE_PLUGIN_DATA`` env var when present.
2. ``<plugin>-<marketplace>`` derived from the script install path
   (``.../plugins/cache/<marketplace>/<plugin>/<version>/scripts/``).
   This matches Claude Code's own data-dir naming and keeps the
   script-side view aligned with the skill-side view even when the env
   var isn't forwarded into the child process — so no inline
   ``CLAUDE_PLUGIN_DATA=...`` prefix is needed in skill bash blocks.
3. Any existing Tinyhat-shaped ``~/.claude/plugins/data/tinyhat*``
   sibling (most-recently-modified first) — for dev checkouts that
   don't live under a marketplace cache.
4. ``<plugin-name>`` from ``plugin.json`` as a last resort.

``reconcile_homes(new_root)`` then pulls any other Tinyhat-shaped
directory (legacy ``~/.claude/tinyhat/`` plus any plugin-data sibling)
into ``new_root`` so a machine that was already split-brained heals on
the first run after this patch.
"""

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


def _cached_install_plugin_id() -> str | None:
    """Derive ``<plugin>-<marketplace>`` from the script install path.

    Claude Code installs marketplace plugins at
    ``~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`` and
    names the matching data dir ``<plugin>-<marketplace>``. When that's
    where the script is running from, return the sanitized id so the
    script-side resolution matches the skill-side ``${CLAUDE_PLUGIN_DATA}``
    without needing the env var to be forwarded explicitly.
    """
    try:
        version_dir = PLUGIN_ROOT
        plugin_dir = version_dir.parent
        marketplace_dir = plugin_dir.parent
        cache_dir = marketplace_dir.parent
    except AttributeError:
        return None
    if cache_dir.name != "cache" or cache_dir.parent.name != "plugins":
        return None
    if not plugin_dir.name or not marketplace_dir.name:
        return None
    return _sanitize_plugin_id(f"{plugin_dir.name}-{marketplace_dir.name}")


def _fallback_plugin_id() -> str:
    inferred = _cached_install_plugin_id()
    if inferred:
        return inferred

    manifest_path = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "tinyhat"

    name = data.get("name")
    if isinstance(name, str) and name.strip():
        return _sanitize_plugin_id(name)
    return "tinyhat"


def _is_tinyhat_shaped(path: Path) -> bool:
    """True when ``path`` holds state a prior Tinyhat run left behind."""
    if not path.is_dir():
        return False
    if (path / "routine.json").exists():
        return True
    for sub in ("latest", "archive"):
        candidate = path / sub
        if candidate.is_dir() and any(candidate.iterdir()):
            return True
    return False


def _scan_sibling_homes(exclude: Path | None = None) -> list[Path]:
    """Return `~/.claude/plugins/data/tinyhat*` dirs that look Tinyhat-shaped.

    Results are sorted most-recently-modified first so callers can
    prefer the newest directory when the env var is missing. ``exclude``
    is skipped (resolved for symlink equality) so reconciliation
    doesn't try to merge a home into itself.
    """
    if not PLUGIN_DATA_ROOT.is_dir():
        return []
    excluded = exclude.resolve() if exclude is not None else None
    homes: list[Path] = []
    for entry in PLUGIN_DATA_ROOT.iterdir():
        if not entry.is_dir():
            continue
        if not entry.name.startswith("tinyhat"):
            continue
        try:
            if excluded is not None and entry.resolve() == excluded:
                continue
        except OSError:
            continue
        if _is_tinyhat_shaped(entry):
            homes.append(entry)
    homes.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return homes


def default_home_root() -> Path:
    """Resolve Tinyhat's home directory.

    Priority:

    1. ``CLAUDE_PLUGIN_DATA`` env var (authoritative when present).
    2. ``<plugin>-<marketplace>`` inferred from the script install path
       (``.../plugins/cache/<marketplace>/<plugin>/<version>/``). This
       matches Claude Code's own per-plugin data-dir naming, so the
       script-side and skill-side views converge without relying on the
       env var being forwarded into the child process.
    3. Any existing Tinyhat-shaped `~/.claude/plugins/data/tinyhat*`
       directory — most recently modified wins. Lets shell-side
       invocations from a dev checkout discover an existing home
       instead of creating a fresh sibling.
    4. ``~/.claude/plugins/data/<plugin-id>`` from ``plugin.json``.
    """
    raw = os.getenv("CLAUDE_PLUGIN_DATA")
    if raw:
        return Path(raw).expanduser()
    inferred = _cached_install_plugin_id()
    if inferred:
        return PLUGIN_DATA_ROOT / inferred
    existing = _scan_sibling_homes()
    if existing:
        return existing[0]
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


def _merge_into(src: Path, dst: Path, *, stderr: TextIO) -> bool:
    """Move ``src`` into ``dst`` and clean the source dir up."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.move(str(src), str(dst))
        print(f"migrated: {src} -> {dst}", file=stderr)
        return True

    _merge_tree(src, dst)
    with contextlib.suppress(OSError):
        src.rmdir()
    if src.exists():
        print(
            f"warn: Tinyhat data still exists at {src}; new writes go to {dst}.",
            file=stderr,
        )
    else:
        print(f"migrated: {src} -> {dst}", file=stderr)
    return True


def reconcile_homes(new_root: Path, *, stderr: TextIO = sys.stderr) -> bool:
    """Pull every other Tinyhat home on disk into ``new_root``.

    Covers both ``~/.claude/tinyhat/`` (the pre-#49 legacy path) and
    any plugin-data sibling (``~/.claude/plugins/data/tinyhat*``) that
    looks Tinyhat-shaped. Safe to call whenever Tinyhat is about to
    read or write state — no-op when nothing is out of place.
    """
    migrated = False
    new_root_resolved: Path | None
    try:
        new_root_resolved = new_root.resolve()
    except OSError:
        new_root_resolved = None

    legacy = LEGACY_HOME_ROOT
    if legacy.exists():
        try:
            legacy_is_target = (
                new_root_resolved is not None and legacy.resolve() == new_root_resolved
            )
        except OSError:
            legacy_is_target = False
        if not legacy_is_target:
            migrated = _merge_into(legacy, new_root, stderr=stderr) or migrated

    for sibling in _scan_sibling_homes(exclude=new_root):
        migrated = _merge_into(sibling, new_root, stderr=stderr) or migrated

    return migrated


def migrate_legacy_home(new_root: Path, *, stderr: TextIO = sys.stderr) -> bool:
    """Backwards-compatible alias for :func:`reconcile_homes`."""
    return reconcile_homes(new_root, stderr=stderr)


def resolve_home_root(home_root: str | Path | None, *, migrate_legacy: bool = True) -> Path:
    root = default_home_root() if home_root is None else Path(home_root).expanduser()
    if home_root is None and migrate_legacy:
        reconcile_homes(root)
    return root
