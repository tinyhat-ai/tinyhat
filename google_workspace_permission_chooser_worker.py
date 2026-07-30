"""Detached watcher for a Tinyhat Google Workspace permission choice."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
import types
from datetime import datetime
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
    DISCONNECT_OWNER_TOKEN_RE,
    GOOGLE_CONNECTION_ID_RE,
    GOOGLE_WORKSPACE_PERMISSION_CHOOSERS_SUFFIX,
    GOOGLE_WORKSPACE_PRESETS,
    GoogleWorkspaceError,
    _cleanup_permission_chooser_worker_state,
    _requested_profile,
    _send_google_workspace_notice,
    _start_connection,
    _validated_permission_chooser_id,
    _write_permission_chooser_worker_ready,
)
from .platform import build_platform_client, computer_api_path

WORKER_SCHEMA = "tinyhat_google_workspace_permission_chooser_worker_v1"


def _selection_ids(result: dict[str, object]) -> tuple[str, ...]:
    """Return one identity choice or one-or-more composable preset ids."""
    raw_selection_ids = result.get("selection_ids")
    if raw_selection_ids is None:
        legacy_selection_id = str(result.get("selection_id") or "").strip()
        raw_selection_ids = [legacy_selection_id] if legacy_selection_id else []
    if (
        not isinstance(raw_selection_ids, list)
        or not raw_selection_ids
        or len(raw_selection_ids) > len(GOOGLE_WORKSPACE_PRESETS)
        or any(
            not isinstance(item, str) or not item or item != item.strip()
            for item in raw_selection_ids
        )
    ):
        raise GoogleWorkspaceError(
            "Google access chooser returned an invalid selection."
        )
    selection_ids = tuple(raw_selection_ids)
    if len(selection_ids) != len(set(selection_ids)):
        raise GoogleWorkspaceError(
            "Google access chooser returned duplicate selections."
        )
    if selection_ids == ("identity_only",):
        return selection_ids
    if "identity_only" in selection_ids or any(
        selection_id not in GOOGLE_WORKSPACE_PRESETS
        for selection_id in selection_ids
    ):
        raise GoogleWorkspaceError(
            "Google access chooser returned an invalid selection."
        )
    return selection_ids


def _load_state(*, chooser_id: str, state_path: Path) -> dict[str, object]:
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GoogleWorkspaceError("Google access chooser state is invalid.") from exc
    if not isinstance(value, dict) or value.get("schema") != WORKER_SCHEMA:
        raise GoogleWorkspaceError("Google access chooser state is invalid.")
    if _validated_permission_chooser_id(value.get("chooser_id")) != chooser_id:
        raise GoogleWorkspaceError("Google access chooser state changed id.")
    owner_token = str(value.get("owner_token") or "")
    if DISCONNECT_OWNER_TOKEN_RE.fullmatch(owner_token) is None:
        raise GoogleWorkspaceError("Google access chooser owner is invalid.")
    account_id = value.get("account_id")
    if account_id is not None and (
        not isinstance(account_id, str)
        or GOOGLE_CONNECTION_ID_RE.fullmatch(account_id) is None
    ):
        raise GoogleWorkspaceError("Google access chooser account is invalid.")
    expires_at = str(value.get("expires_at") or "")
    try:
        parsed_expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoogleWorkspaceError("Google access chooser expiry is invalid.") from exc
    if parsed_expiry.tzinfo is None or parsed_expiry.utcoffset() is None:
        raise GoogleWorkspaceError("Google access chooser expiry is invalid.")
    return {
        "owner_token": owner_token,
        "account_id": account_id,
        "expires_at_epoch": parsed_expiry.timestamp(),
    }


def _complete(
    *,
    chooser_id: str,
    owner_token: str,
    outcome: str,
    error_code: str | None = None,
) -> None:
    client, platform_auth = build_platform_client()
    payload: dict[str, object] = {
        "owner_token": owner_token,
        "outcome": outcome,
    }
    if error_code:
        payload["error_code"] = error_code
    client.post_json(
        computer_api_path(
            platform_auth,
            f"{GOOGLE_WORKSPACE_PERMISSION_CHOOSERS_SUFFIX}/{chooser_id}/complete",
        ),
        payload,
    )


def run_worker(*, chooser_id: str, state_path: Path) -> None:
    validated_id = _validated_permission_chooser_id(chooser_id)
    state = _load_state(chooser_id=validated_id, state_path=state_path)
    owner_token = str(state["owner_token"])
    account_id = state["account_id"]
    expires_at_epoch = float(state["expires_at_epoch"])
    try:
        _write_permission_chooser_worker_ready(
            chooser_id=validated_id,
            state_path=state_path,
        )
        client, platform_auth = build_platform_client()
        while time.time() < expires_at_epoch:
            result = client.post_json(
                computer_api_path(
                    platform_auth,
                    f"{GOOGLE_WORKSPACE_PERMISSION_CHOOSERS_SUFFIX}/{validated_id}/poll",
                ),
                {"owner_token": owner_token},
            )
            status = str(result.get("status") or "").strip().lower()
            if status == "waiting":
                time.sleep(max(0.25, int(result.get("poll_after_ms") or 750) / 1000))
                continue
            if status in {
                "custom",
                "completed",
                "failed",
                "expired",
                "superseded",
            }:
                return
            if status != "selected":
                raise GoogleWorkspaceError("Google access chooser returned an invalid state.")
            selection_ids = _selection_ids(result)
            if selection_ids == ("identity_only",):
                profile = _requested_profile(None)
            else:
                profile = _requested_profile(None, presets=list(selection_ids))
            started = _start_connection(
                profile=profile,
                account_id=account_id if isinstance(account_id, str) else None,
                exact_permissions=isinstance(account_id, str),
            )
            if started.get("status") != "waiting_for_user":
                raise GoogleWorkspaceError(
                    "Google access chooser could not start Google authorization."
                )
            _complete(
                chooser_id=validated_id,
                owner_token=owner_token,
                outcome="completed",
            )
            return
        with contextlib.suppress(Exception):
            _complete(
                chooser_id=validated_id,
                owner_token=owner_token,
                outcome="failed",
                error_code="expired",
            )
    except Exception:
        with contextlib.suppress(Exception):
            _complete(
                chooser_id=validated_id,
                owner_token=owner_token,
                outcome="failed",
                error_code="oauth_start_failed",
            )
        with contextlib.suppress(Exception):
            _send_google_workspace_notice("failed")
        raise
    finally:
        _cleanup_permission_chooser_worker_state(state_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chooser-id", required=True)
    parser.add_argument("--state-path", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run_worker(
            chooser_id=args.chooser_id,
            state_path=Path(args.state_path),
        )
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
