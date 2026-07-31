"""Detached worker for owner-confirmed Slack disconnects."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import re
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

if __package__ in {None, ""}:
    package_dir = Path(__file__).resolve().parent
    parent_dir = package_dir.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    package = sys.modules.get("tinyhat")
    if package is None:
        package = types.ModuleType("tinyhat")
        package.__file__ = str(package_dir / "__init__.py")
        package.__path__ = [str(package_dir)]  # type: ignore[attr-defined]
        sys.modules["tinyhat"] = package
    __package__ = "tinyhat"

from .platform import PlatformError, build_platform_client, computer_api_path
from .slack_disconnect import SCHEMA, disconnect_slack_locally

TERMINAL_STATUSES = frozenset({"removed", "cancelled", "expired", "failed", "superseded"})
STATE_DIR = Path.home() / ".tinyhat" / "slack-disconnect-workers"


def _deadline(expires_at: str) -> float:
    try:
        value = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return time.time() + 10 * 60
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _worker_lock(removal_id: str) -> tuple[Path, TextIO] | None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.chmod(0o700)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", removal_id)
    path = STATE_DIR / f"{safe_id}.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return path, handle


def run_worker(*, handoff_id: str, removal_id: str, expires_at: str) -> None:
    lock = _worker_lock(removal_id)
    if lock is None:
        return
    lock_path, lock_handle = lock
    client, platform_auth = build_platform_client(timeout_seconds=20)
    state_path = computer_api_path(
        platform_auth,
        f"slack/disconnect/v1/{handoff_id}/removals/{removal_id}",
    )
    result_path = computer_api_path(
        platform_auth,
        f"slack/disconnect/v1/{handoff_id}/result",
    )
    deadline = _deadline(expires_at)
    try:
        while time.time() < deadline:
            try:
                state = client.get_json(state_path)
            except PlatformError:
                time.sleep(2)
                continue
            status = str(state.get("status") or "").strip()
            if status == "confirmed":
                result = disconnect_slack_locally()
                result["schema"] = SCHEMA
                result["removal_id"] = removal_id
                while time.time() < deadline:
                    try:
                        client.post_json(result_path, result)
                    except PlatformError:
                        time.sleep(2)
                        continue
                    return
                return
            if status in TERMINAL_STATUSES or status in {"queuing", "queued"}:
                return
            time.sleep(max(1.0, float(state.get("poll_after_ms") or 2000) / 1000))
    finally:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        finally:
            lock_handle.close()
            with contextlib.suppress(OSError):
                lock_path.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-id", required=True)
    parser.add_argument("--removal-id", required=True)
    parser.add_argument("--expires-at", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_worker(
        handoff_id=args.handoff_id,
        removal_id=args.removal_id,
        expires_at=args.expires_at,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
