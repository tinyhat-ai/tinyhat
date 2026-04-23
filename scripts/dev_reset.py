#!/usr/bin/env python3
"""INTERNAL DEV ONLY — wipe Tinyhat state for a fresh first-run test.

Removes every byte the Tinyhat plugin wrote on the local machine, plus every
registration of the plugin, so the next `/plugin install` cycle is the real
new-user path. Must not be shipped to end users — see issue #55.

Default is dry-run. Pass --commit to actually remove. Pass --full to also
remove our marketplace registration (the true pre-onboarding state).

Targets:
    ~/.claude/plugins/data/tinyhat*                       plugin-data dirs
    ~/.claude/plugins/.install-manifests/tinyhat@*.json   install manifests
    ~/.claude/plugins/cache/<marketplace>/tinyhat/        per-marketplace cache
    ~/.claude/tinyhat/                                    legacy pre-#49 home
    <tempdir>/tinyhat-snapshot.json, tinyhat-snapshot-detail.json,   pipeline hand-off
    <tempdir>/tinyhat-analysis.json
    ~/.claude/plugins/installed_plugins.json              entries keyed tinyhat@*
    ~/.claude/plugins/known_marketplaces.json             tinyloop entry (--full)
    ~/.claude/plugins/marketplaces/<ours>/                cloned market (--full)

Never touches: ~/.claude/projects/, ~/.claude/rc-dashboard/, the checked-out
tinyhat repo, other plugins' data, or the CLAUDE_PLUGIN_DATA env var.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HOME = Path.home()
CLAUDE_ROOT = HOME / ".claude"
PLUGINS_ROOT = CLAUDE_ROOT / "plugins"

# Keys in known_marketplaces.json that identify "our" marketplace. The
# marketplace's declared name is "tinyloop"; the repo behind it is
# tinyhat-ai/tinyhat. Either signal is enough.
OUR_MARKETPLACE_NAMES = {"tinyloop"}
OUR_MARKETPLACE_REPOS = {"tinyhat-ai/tinyhat"}


class Target:
    __slots__ = ("kind", "path", "detail", "gated")

    def __init__(self, kind: str, path: Path, detail: str = "", *, gated: bool = False):
        self.kind = kind
        self.path = path
        self.detail = detail
        self.gated = gated

    def describe(self) -> str:
        suffix = f" ({self.detail})" if self.detail else ""
        return f"[{self.kind}] {self.path}{suffix}"


def _glob(parent: Path, pattern: str) -> list[Path]:
    if not parent.is_dir():
        return []
    return sorted(parent.glob(pattern))


def _enumerate_plugin_data() -> list[Target]:
    # Both "tinyhat" and any legacy split-brain names like "tinyhat@tinyloop".
    parent = PLUGINS_ROOT / "data"
    return [Target("data-dir", p) for p in _glob(parent, "tinyhat*")]


def _enumerate_install_manifests() -> list[Target]:
    parent = PLUGINS_ROOT / ".install-manifests"
    return [Target("install-manifest", p) for p in _glob(parent, "tinyhat@*.json")]


def _enumerate_cache() -> list[Target]:
    # Layout: ~/.claude/plugins/cache/<marketplace>/tinyhat/
    cache_root = PLUGINS_ROOT / "cache"
    if not cache_root.is_dir():
        return []
    out: list[Target] = []
    for marketplace_dir in sorted(cache_root.iterdir()):
        if not marketplace_dir.is_dir():
            continue
        candidate = marketplace_dir / "tinyhat"
        if candidate.exists():
            out.append(Target("cache", candidate, detail=f"marketplace={marketplace_dir.name}"))
    return out


def _enumerate_legacy_home() -> list[Target]:
    legacy = CLAUDE_ROOT / "tinyhat"
    return [Target("legacy-home", legacy)] if legacy.exists() else []


def _enumerate_temp_files() -> list[Target]:
    tmp = Path(tempfile.gettempdir())
    names = (
        "tinyhat-snapshot.json",
        "tinyhat-snapshot-detail.json",
        "tinyhat-analysis.json",
    )
    return [Target("temp-file", tmp / n) for n in names if (tmp / n).exists()]


def _enumerate_installed_plugins_entries() -> list[Target]:
    # Keyed removal — we rewrite the file, we don't delete it.
    path = PLUGINS_ROOT / "installed_plugins.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        return []
    out: list[Target] = []
    for key in sorted(plugins):
        if isinstance(key, str) and key.startswith("tinyhat@"):
            out.append(Target("installed-plugins-entry", path, detail=f"key={key}"))
    return out


def _marketplace_is_ours(name: str, entry: dict) -> bool:
    if name in OUR_MARKETPLACE_NAMES:
        return True
    source = entry.get("source") if isinstance(entry, dict) else None
    if isinstance(source, dict):
        repo = source.get("repo")
        if isinstance(repo, str) and repo in OUR_MARKETPLACE_REPOS:
            return True
    return False


def _enumerate_marketplace_registrations() -> list[Target]:
    out: list[Target] = []
    path = PLUGINS_ROOT / "known_marketplaces.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            for name, entry in sorted(data.items()):
                if _marketplace_is_ours(name, entry):
                    out.append(
                        Target(
                            "marketplace-registration",
                            path,
                            detail=f"key={name}",
                            gated=True,
                        )
                    )
    # Cloned marketplace source on disk.
    market_dir = PLUGINS_ROOT / "marketplaces"
    if market_dir.is_dir():
        for child in sorted(market_dir.iterdir()):
            if child.is_dir() and child.name in OUR_MARKETPLACE_NAMES:
                out.append(Target("marketplace-clone", child, gated=True))
    return out


def enumerate_all(*, include_full: bool) -> list[Target]:
    targets: list[Target] = []
    targets += _enumerate_plugin_data()
    targets += _enumerate_install_manifests()
    targets += _enumerate_cache()
    targets += _enumerate_legacy_home()
    targets += _enumerate_temp_files()
    targets += _enumerate_installed_plugins_entries()
    if include_full:
        targets += _enumerate_marketplace_registrations()
    return targets


def _remove_fs_target(target: Target) -> None:
    p = target.path
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    else:
        p.unlink(missing_ok=True)


def _rewrite_installed_plugins(keys_to_drop: set[str]) -> list[str]:
    path = PLUGINS_ROOT / "installed_plugins.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    plugins = data.get("plugins") or {}
    dropped = [k for k in plugins if k in keys_to_drop]
    for k in dropped:
        plugins.pop(k, None)
    data["plugins"] = plugins
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return dropped


def _rewrite_known_marketplaces(names_to_drop: set[str]) -> list[str]:
    path = PLUGINS_ROOT / "known_marketplaces.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    dropped = [name for name in list(data) if name in names_to_drop]
    for name in dropped:
        data.pop(name, None)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return dropped


def _commit(targets: list[Target]) -> list[tuple[Target, str | None]]:
    results: list[tuple[Target, str | None]] = []

    # File/dir targets.
    for t in targets:
        if t.kind in {"installed-plugins-entry", "marketplace-registration"}:
            continue
        try:
            _remove_fs_target(t)
            results.append((t, None))
        except OSError as exc:
            results.append((t, str(exc)))

    # installed_plugins.json keyed rewrite (one pass for all keys).
    ip_keys = {
        t.detail.removeprefix("key=") for t in targets if t.kind == "installed-plugins-entry"
    }
    if ip_keys:
        try:
            dropped = _rewrite_installed_plugins(ip_keys)
            for t in targets:
                if t.kind == "installed-plugins-entry":
                    key = t.detail.removeprefix("key=")
                    err = None if key in dropped else "not present"
                    results.append((t, err))
        except (OSError, json.JSONDecodeError) as exc:
            for t in targets:
                if t.kind == "installed-plugins-entry":
                    results.append((t, str(exc)))

    # known_marketplaces.json keyed rewrite.
    km_names = {
        t.detail.removeprefix("key=") for t in targets if t.kind == "marketplace-registration"
    }
    if km_names:
        try:
            dropped = _rewrite_known_marketplaces(km_names)
            for t in targets:
                if t.kind == "marketplace-registration":
                    name = t.detail.removeprefix("key=")
                    err = None if name in dropped else "not present"
                    results.append((t, err))
        except (OSError, json.JSONDecodeError) as exc:
            for t in targets:
                if t.kind == "marketplace-registration":
                    results.append((t, str(exc)))

    return results


def _print_cross_version_notes(out) -> None:
    env = os.getenv("CLAUDE_PLUGIN_DATA")
    if env:
        print(
            f"note: CLAUDE_PLUGIN_DATA is set to {env!r}. Data under that path was NOT auto-detected",
            file=out,
        )
        print(
            "      by this script — if you use it, wipe that directory yourself.",
            file=out,
        )


def _print_kept_note(out) -> None:
    print("", file=out)
    print("kept (by design):", file=out)
    print("  - ~/.claude/projects/   Claude Code session transcripts + auto-memory", file=out)
    print("  - ~/.claude/rc-dashboard/  unrelated logs (different 'tinyhat')", file=out)
    print("  - this repo checkout     the source of truth", file=out)
    print("  - other plugins' data under ~/.claude/plugins/", file=out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="INTERNAL DEV ONLY: wipe Tinyhat state for a fresh first-run test.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually remove targets. Without this, the script is a dry-run.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Also remove our marketplace registration (pre-onboarding state).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable summary on stdout instead of prose.",
    )
    args = parser.parse_args(argv)

    out = sys.stdout
    targets = enumerate_all(include_full=args.full)

    if not targets:
        if args.json:
            payload: dict = {"mode": "commit" if args.commit else "dry-run"}
            if args.commit:
                payload["removed"] = []
                payload["errors"] = []
            else:
                payload["would_remove"] = []
            print(json.dumps(payload, indent=2), file=out)
        else:
            print("tinyhat dev reset: already clean. Nothing to remove.", file=out)
            if not args.full:
                print(
                    "(not checking marketplace registration; pass --full if you need a nuclear reset.)",
                    file=out,
                )
            _print_cross_version_notes(out)
        return 0

    if not args.commit:
        if args.json:
            payload = {
                "mode": "dry-run",
                "would_remove": [
                    {"kind": t.kind, "path": str(t.path), "detail": t.detail} for t in targets
                ],
            }
            print(json.dumps(payload, indent=2), file=out)
        else:
            print(
                "tinyhat dev reset — DRY RUN. Pass --commit to actually remove.",
                file=out,
            )
            print("", file=out)
            print("would remove:", file=out)
            for t in targets:
                print(f"  {t.describe()}", file=out)
            if not args.full:
                print("", file=out)
                print(
                    "(scoped reset: marketplace registration left intact. Pass --full for a nuclear reset.)",
                    file=out,
                )
            _print_kept_note(out)
            _print_cross_version_notes(out)
        return 0

    results = _commit(targets)
    removed = [t for t, err in results if err is None]
    errors = [(t, err) for t, err in results if err is not None]

    if args.json:
        payload = {
            "mode": "commit",
            "removed": [{"kind": t.kind, "path": str(t.path), "detail": t.detail} for t in removed],
            "errors": [
                {"kind": t.kind, "path": str(t.path), "detail": t.detail, "error": err}
                for t, err in errors
            ],
        }
        print(json.dumps(payload, indent=2), file=out)
    else:
        print(f"tinyhat dev reset: removed {len(removed)} target(s).", file=out)
        for t in removed:
            print(f"  removed  {t.describe()}", file=out)
        for t, err in errors:
            print(f"  ERROR    {t.describe()}: {err}", file=sys.stderr)
        _print_kept_note(out)
        _print_cross_version_notes(out)

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
