"""Detached worker for a Tinyhat Google Workspace OAuth handoff."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
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
    GoogleWorkspaceError,
    GoogleWorkspaceWorkerHandoff,
    _claim_superseded,
    _cleanup_worker_state,
    _handoff_owner_token,
    _lifecycle_lock,
    _normalize_workspace_scopes,
    _normalize_workspace_services,
    _poll_and_install,
    _profile_for_capability_bundle,
    _remove_active_handoff_marker_if_matches,
    _validated_capability_bundle,
    _validated_connection_id,
    _validated_handoff_id,
)
from .platform import build_platform_client

GENERATION_MIN_LENGTH = 32
GENERATION_MAX_LENGTH = 256


def run_worker(*, handoff_id: str, key_path: Path) -> None:
    validated_handoff_id = _validated_handoff_id(handoff_id)
    owner_token: str | None = None
    try:
        try:
            private_key_pem = key_path.read_text(encoding="utf-8")
            generation = (key_path.parent / "generation").read_text(encoding="ascii")
            if (
                not GENERATION_MIN_LENGTH <= len(generation) <= GENERATION_MAX_LENGTH
                or generation.strip() != generation
            ):
                raise GoogleWorkspaceError("The one-time handoff generation is invalid.")
            metadata = json.loads(
                (key_path.parent / "handoff-metadata.json").read_text(encoding="utf-8")
            )
            if not isinstance(metadata, dict):
                raise GoogleWorkspaceError("The one-time handoff metadata is invalid.")
            capability_bundle = _validated_capability_bundle(
                metadata.get("capability_bundle")
            )
            profile = _profile_for_capability_bundle(capability_bundle)
            services = _normalize_workspace_services(
                metadata.get("services"),
                expected=profile.services,
            )
            scopes = _normalize_workspace_scopes(
                metadata.get("scopes"),
                expected=profile.scopes,
            )
            connection_action = metadata.get("connection_action")
            if connection_action not in {"add", "replace"}:
                raise GoogleWorkspaceError("The one-time handoff action is invalid.")
            target_connection_id = _validated_connection_id(
                metadata.get("target_connection_id"),
                required=True,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, GoogleWorkspaceError):
            client, platform_auth = build_platform_client()
            _claim_superseded(
                client=client,
                platform_auth=platform_auth,
                handoff_id=validated_handoff_id,
            )
            return
        owner_token = _handoff_owner_token(generation)
        client, platform_auth = build_platform_client()
        _poll_and_install(
            GoogleWorkspaceWorkerHandoff(
                client=client,
                platform_auth=platform_auth,
                handoff_id=validated_handoff_id,
                owner_token=owner_token,
                private_key_pem=private_key_pem,
                expected_capability_bundle=capability_bundle,
                expected_services=services,
                expected_scopes=scopes,
                connection_action=connection_action,
                target_connection_id=target_connection_id,
            )
        )
        generation = ""
        private_key_pem = ""
    finally:
        if owner_token is not None:
            with contextlib.suppress(Exception), _lifecycle_lock():
                _remove_active_handoff_marker_if_matches(
                    handoff_id=validated_handoff_id,
                    owner_token=owner_token,
                )
        _cleanup_worker_state(key_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-id", required=True)
    parser.add_argument("--key-path", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        run_worker(
            handoff_id=args.handoff_id,
            key_path=Path(args.key_path),
        )
    except Exception:
        # The worker may handle tokens and local state paths. Its public failure
        # signal is only the process status; never emit exception details.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
