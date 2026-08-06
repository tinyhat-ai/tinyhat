"""Detached worker for Tinyhat private secret handoffs.

Hermes may execute tools in a short-lived process. The handoff must keep
polling after the tool returns, so this worker owns the one-time private key
until the user submits, the Computer saves the secret, or the handoff expires.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import shutil
import sys
import time
import types
from contextlib import suppress
from pathlib import Path

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

from .platform import build_platform_client, computer_api_path
from .secret_handoff import (
    DEFAULT_EXPIRES_IN_SECONDS,
    SecretHandoffError,
    _claim_handoff,
    _install_submitted_secret,
    _parse_expires_at,
    _public_failure_message,
)


def run_worker(
    *,
    handoff_id: str,
    key_path: Path,
    expires_in_seconds: int = DEFAULT_EXPIRES_IN_SECONDS,
    hat_handle: str | None = None,
    persistent: bool = False,
) -> None:
    client, platform_auth = build_platform_client()
    if persistent:
        _run_persistent_hat_worker(
            client=client,
            platform_auth=platform_auth,
            handoff_id=handoff_id,
            key_path=key_path,
            hat_handle=hat_handle,
        )
        return
    try:
        private_key_pem = key_path.read_text(encoding="utf-8")
        deadline = time.time() + max(1, int(expires_in_seconds))
        last_status = ""
        last_handoff_kind = ""
        while time.time() < deadline:
            state = client.get_json(
                computer_api_path(
                    platform_auth,
                    f"private-secret-handoffs/v1/{handoff_id}",
                )
            )
            parsed_deadline = _parse_expires_at(state.get("expires_at"))
            if parsed_deadline is not None:
                deadline = parsed_deadline
            status = str(state.get("status") or "").strip()
            last_status = status
            last_handoff_kind = str(state.get("handoff_kind") or "").strip()
            if status == "submitted":
                installed = _install_submitted_secret(
                    client=client,
                    platform_auth=platform_auth,
                    handoff_id=handoff_id,
                    private_key_pem=private_key_pem,
                    state=state,
                    hat_handle=hat_handle,
                )
                if installed:
                    return
            if status in {"claimed", "expired"}:
                return
            if status == "failed" and state.get("handoff_kind") != "slack_connection":
                return
            poll_after = max(1.0, float(state.get("poll_after_ms") or 2000) / 1000)
            time.sleep(poll_after)
        if last_status == "failed" and last_handoff_kind == "slack_connection":
            return
        _claim_handoff(
            client,
            platform_auth,
            handoff_id,
            installed=False,
            message="Secret entry expired before a value was submitted.",
        )
    except Exception as exc:
        try:
            _claim_handoff(
                client,
                platform_auth,
                handoff_id,
                installed=False,
                message=_public_failure_message(exc),
            )
        except Exception:
            pass
        if isinstance(exc, SecretHandoffError):
            raise SystemExit(1) from exc
        raise
    finally:
        _cleanup_key_path(key_path)


def _run_persistent_hat_worker(
    *,
    client,
    platform_auth: str,
    handoff_id: str,
    key_path: Path,
    hat_handle: str | None,
) -> None:
    """Keep the Hat key local so its preview can reopen the same bundle form."""
    lock_path = key_path.with_suffix(".worker.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        private_key_pem = key_path.read_text(encoding="utf-8")
        while True:
            try:
                state = client.get_json(
                    computer_api_path(
                        platform_auth,
                        f"private-secret-handoffs/v1/{handoff_id}",
                    )
                )
                if str(state.get("status") or "").strip() == "submitted":
                    _install_submitted_secret(
                        client=client,
                        platform_auth=platform_auth,
                        handoff_id=handoff_id,
                        private_key_pem=private_key_pem,
                        state=state,
                        hat_handle=hat_handle,
                    )
                poll_after = max(
                    1.0,
                    float(state.get("poll_after_ms") or 2000) / 1000,
                )
            except Exception as exc:  # keep preview edits available after retries
                with suppress(Exception):
                    _claim_handoff(
                        client,
                        platform_auth,
                        handoff_id,
                        installed=False,
                        message=_public_failure_message(exc),
                    )
                poll_after = 3.0
            time.sleep(poll_after)


def _cleanup_key_path(key_path: Path) -> None:
    try:
        key_path.unlink()
    except OSError:
        pass
    try:
        shutil.rmtree(key_path.parent)
    except OSError:
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-id", required=True)
    parser.add_argument("--key-path", required=True)
    parser.add_argument(
        "--expires-in-seconds",
        type=int,
        default=DEFAULT_EXPIRES_IN_SECONDS,
    )
    parser.add_argument("--hat-handle")
    parser.add_argument("--persistent", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_worker(
        handoff_id=args.handoff_id,
        key_path=Path(args.key_path),
        expires_in_seconds=args.expires_in_seconds,
        hat_handle=args.hat_handle,
        persistent=args.persistent,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
