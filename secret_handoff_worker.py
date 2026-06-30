"""Detached worker for Tinyhat private secret handoffs.

Hermes may execute tools in a short-lived process. The handoff must keep
polling after the tool returns, so this worker owns the one-time private key
until the user submits, the Computer saves the secret, or the handoff expires.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
import types
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

from .platform import build_platform_client
from .platform import computer_api_path
from .secret_handoff import (
    DEFAULT_EXPIRES_IN_SECONDS,
    SecretHandoffError,
    _claim_handoff,
    _install_submitted_secret,
    _parse_expires_at,
    _public_failure_message,
)


def run_worker(*, handoff_id: str, key_path: Path) -> None:
    client, platform_auth = build_platform_client()
    try:
        private_key_pem = key_path.read_text(encoding="utf-8")
        deadline = time.time() + DEFAULT_EXPIRES_IN_SECONDS
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
            if status == "submitted":
                _install_submitted_secret(
                    client=client,
                    platform_auth=platform_auth,
                    handoff_id=handoff_id,
                    private_key_pem=private_key_pem,
                    state=state,
                )
                return
            if status in {"claimed", "expired", "failed"}:
                return
            poll_after = max(1.0, float(state.get("poll_after_ms") or 2000) / 1000)
            time.sleep(poll_after)
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_worker(handoff_id=args.handoff_id, key_path=Path(args.key_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
