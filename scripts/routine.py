#!/usr/bin/env python3
"""Tinyhat routine state — routine.json + run-stamp.txt.

Subcommands:
    routine.py status         Print current state + last run date. Exit 0.
    routine.py on             Set enabled=true. Exit 0.
    routine.py off            Set enabled=false. Exit 0.
    routine.py check          Exit 0 if a run should fire today (enabled +
                              no run-stamp for today). Exit 1 otherwise.
                              Also prints a one-line reason.
    routine.py clear-archive  Delete everything under archive/, keep latest/.
    routine.py where          Print the paths Tinyhat reads and writes.

Everything lives under ~/.claude/tinyhat/. No network calls, no daemons.
The adaptive daily trigger is implemented by having the skill invoke this
script with `check` on every skill load and firing a background review
when exit status is 0.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_HOME_ROOT = Path.home() / ".claude" / "tinyhat"


def _load_routine(root: Path) -> dict:
    path = root / "routine.json"
    if not path.is_file():
        return {"enabled": True, "installed_at": datetime.now(timezone.utc).isoformat()}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("routine.json must be an object")
        return data
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"warn: routine.json unreadable ({exc}); treating as default-on.", file=sys.stderr)
        return {"enabled": True, "installed_at": datetime.now(timezone.utc).isoformat()}


def _save_routine(root: Path, data: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "routine.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def _last_run_date(root: Path) -> str:
    path = root / "latest" / "run-stamp.txt"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def cmd_status(root: Path) -> int:
    data = _load_routine(root)
    last = _last_run_date(root)
    state = "on" if data.get("enabled", True) else "off"
    print(f"routine: {state}")
    print(f"last run: {last or '(never)'}")
    print(f"home: {root}")
    return 0


def cmd_on(root: Path) -> int:
    data = _load_routine(root)
    data["enabled"] = True
    _save_routine(root, data)
    print("routine: on")
    return 0


def cmd_off(root: Path) -> int:
    data = _load_routine(root)
    data["enabled"] = False
    _save_routine(root, data)
    print("routine: off")
    return 0


def cmd_check(root: Path) -> int:
    """Return 0 if a daily run should fire now.

    Exit 0 only when routine is enabled AND the last run's date is not
    today. The skill uses this as a gate before launching a background
    review.
    """
    data = _load_routine(root)
    if not data.get("enabled", True):
        print("skip: routine disabled")
        return 1
    last = _last_run_date(root)
    today = _today()
    if last == today:
        print(f"skip: already ran today ({last})")
        return 1
    print(f"fire: last_run={last or '(never)'}, today={today}")
    return 0


def cmd_clear_archive(root: Path) -> int:
    archive_dir = root / "archive"
    if not archive_dir.is_dir():
        print("archive: nothing to clear")
        return 0
    removed = 0
    for entry in archive_dir.iterdir():
        if entry.is_dir():
            try:
                shutil.rmtree(entry)
                removed += 1
            except OSError as exc:
                print(f"warn: failed to remove {entry}: {exc}", file=sys.stderr)
    print(f"archive: removed {removed} dated directories. latest/ preserved.")
    return 0


def cmd_where(root: Path) -> int:
    print("Tinyhat reads:")
    print("  ~/.claude/projects/**/*.jsonl                  (Claude Code CLI + desktop Code tab)")
    print("  ~/Library/Application Support/Claude/          (Cowork transcripts, session wrappers)")
    print("  ~/.claude/skills/, ~/.claude/plugins/           (skill inventory)")
    print("  ~/.gstack/analytics/skill-usage.jsonl          (optional local telemetry)")
    print("Tinyhat writes:")
    print(f"  {root}/routine.json")
    print(f"  {root}/latest/report.md")
    print(f"  {root}/latest/report.html")
    print(f"  {root}/latest/run-stamp.txt")
    print(f"  {root}/archive/YYYY-MM-DD/report.{{md,html}}  (up to 31 dated dirs)")
    print(f"  {root}/feedback.jsonl                         (local-only feedback)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Tinyhat routine state.")
    parser.add_argument(
        "--home-root",
        default=str(DEFAULT_HOME_ROOT),
        help="Root directory for Tinyhat state (default: ~/.claude/tinyhat)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("status", "on", "off", "check", "clear-archive", "where"):
        sub.add_parser(name)
    args = parser.parse_args()

    root = Path(args.home_root).expanduser()
    commands = {
        "status": cmd_status,
        "on": cmd_on,
        "off": cmd_off,
        "check": cmd_check,
        "clear-archive": cmd_clear_archive,
        "where": cmd_where,
    }
    return commands[args.cmd](root)


if __name__ == "__main__":
    raise SystemExit(main())
