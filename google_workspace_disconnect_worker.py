"""Detached worker for a Tinyhat Google Workspace disconnect intent."""

from __future__ import annotations

import argparse
import os
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

from .google_workspace import (
    DISCONNECT_WORKER_READY_TIMEOUT_SECONDS,
    _cleanup_disconnect_worker_state,
    _disconnect_completion_receipt_path,
    _load_disconnect_completion_receipt,
    _load_disconnect_worker_intent,
    _poll_disconnect_intent,
    _resume_delete_pending_receipt,
    _retry_disconnect_completion,
    _validated_handoff_id,
    _write_disconnect_completion_receipt,
    _write_disconnect_worker_ready,
)
from .platform import PlatformClient, build_platform_client

RETAINED_COMPLETION_OUTCOMES = frozenset(
    {"completion_pending", "expiry_completion_pending", "deletion_claim_pending"}
)


def _build_platform_client_for_ready_worker() -> tuple[PlatformClient, str]:
    """Retry transient startup failures only within the activation handshake."""
    deadline = time.monotonic() + max(
        0.0,
        DISCONNECT_WORKER_READY_TIMEOUT_SECONDS - 0.5,
    )
    while True:
        try:
            return build_platform_client()
        except Exception:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(0.25, remaining))


def run_worker(*, intent_id: str, state_path: Path) -> None:
    """Poll one owner-bound intent and clean its owner-only scratch state."""
    clean_intent_id = _validated_handoff_id(intent_id)
    receipt_path = _disconnect_completion_receipt_path(
        intent_id=clean_intent_id,
        state_path=state_path,
    )
    outcome: str | None = None
    try:
        client, platform_auth = _build_platform_client_for_ready_worker()
        intent = _load_disconnect_worker_intent(
            intent_id=clean_intent_id,
            state_path=state_path,
            client=client,
            platform_auth=platform_auth,
        )
        _write_disconnect_worker_ready(
            intent_id=clean_intent_id,
            state_path=state_path,
        )
        receipt = _load_disconnect_completion_receipt(
            intent=intent,
            state_path=state_path,
        )
        if receipt is not None and receipt.phase == "delete_pending":
            resume_status = _resume_delete_pending_receipt(
                intent=intent,
                state_path=state_path,
            )
            if resume_status == "completion_pending":
                receipt = _load_disconnect_completion_receipt(
                    intent=intent,
                    state_path=state_path,
                )
            elif resume_status == "delete_required":
                # The crash happened before unlink. Resume the already-confirmed
                # poll path, which revalidates generation and assignment before
                # allowing the one still-pending delete.
                receipt = None
            else:
                outcome = resume_status
                receipt = None
        if receipt is not None:
            acknowledged = _retry_disconnect_completion(
                intent=intent,
                outcome=receipt.outcome,
                error_code=receipt.error_code,
            )
            if receipt.outcome == "disconnected":
                outcome = "disconnected" if acknowledged else "completion_pending"
            else:
                outcome = "expired" if acknowledged else "expiry_completion_pending"
        elif outcome is None:

            def record_completion(
                phase: str,
                completion_outcome: str,
                error_code: str | None,
            ) -> None:
                _write_disconnect_completion_receipt(
                    intent=intent,
                    state_path=state_path,
                    phase=phase,
                    outcome=completion_outcome,
                    error_code=error_code,
                )

            outcome = _poll_disconnect_intent(
                intent,
                record_completion_receipt=record_completion,
            )
    finally:
        receipt_unacknowledged = outcome is None and os.path.lexists(receipt_path)
        if outcome not in RETAINED_COMPLETION_OUTCOMES and not receipt_unacknowledged:
            _cleanup_disconnect_worker_state(state_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent-id", required=True)
    parser.add_argument("--state-path", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run_worker(
            intent_id=args.intent_id,
            state_path=Path(args.state_path),
        )
    except Exception:
        # Owner tokens and local state paths are private. Process status is the
        # only public failure signal; never print exception details.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
