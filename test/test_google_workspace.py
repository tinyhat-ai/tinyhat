"""Google Workspace plugin connection tests."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import stat
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib import parse

REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT = REPO_ROOT.parent
sys.path.insert(0, str(PARENT))

if REPO_ROOT.name != "tinyhat":
    spec = importlib.util.spec_from_file_location(
        "tinyhat",
        REPO_ROOT / "__init__.py",
        submodule_search_locations=[str(REPO_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load local tinyhat package for tests.")
    tinyhat = importlib.util.module_from_spec(spec)
    sys.modules["tinyhat"] = tinyhat
    spec.loader.exec_module(tinyhat)
else:
    import tinyhat  # type: ignore[no-redef]

from tinyhat import context as tinyhat_context  # noqa: E402
from tinyhat import google_workspace as workspace  # noqa: E402
from tinyhat import (  # noqa: E402
    google_workspace_disconnect_worker,
    google_workspace_worker,
    schemas,
    tools,
)

READONLY_BUNDLE = "google_workspace_readonly_v1"
READONLY_SERVICES = ["identity", "gmail", "calendar", "drive"]
READONLY_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
GMAIL_SEND_BUNDLE = "google_workspace_gmail_send_v1"
GMAIL_SEND_SCOPES = [
    *READONLY_SCOPES,
    "https://www.googleapis.com/auth/gmail.send",
]
CALENDAR_WRITE_BUNDLE = "google_workspace_calendar_write_v1"
CALENDAR_WRITE_SCOPES = [
    *READONLY_SCOPES,
    "https://www.googleapis.com/auth/calendar.events",
]
GMAIL_SEND_CALENDAR_WRITE_BUNDLE = "google_workspace_gmail_send_calendar_write_v1"
GMAIL_SEND_CALENDAR_WRITE_SCOPES = [
    *GMAIL_SEND_SCOPES,
    "https://www.googleapis.com/auth/calendar.events",
]
PLATFORM_BASE_URL = "https://api.example.test"
PREPARE_PATH = "/hapi/v1/public/tinyhat/google-workspace/oauth/prepare/v1"


def prepare_authorization_url() -> str:
    return f"{PLATFORM_BASE_URL}{PREPARE_PATH}#gwol1.1.{'a' * 64}"


def direct_google_authorization_url() -> str:
    return (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        "client_id=central-public-client&state=opaque"
    )


def credential_envelope(
    *,
    bundle: str = READONLY_BUNDLE,
    scopes: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema": "tinyhat_google_workspace_credentials_v1",
        "capability_bundle": bundle,
        "services": READONLY_SERVICES.copy(),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "central-public-client.apps.googleusercontent.com",
        "access_token": "test-access-value",
        "refresh_token": "test-refresh-value",
        "token_type": "Bearer",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "scopes": list(scopes or READONLY_SCOPES),
        "google_subject": "google-user-123",
        "email": "owner@example.com",
        "email_verified": True,
        "tinyhat_assignment_binding": "assignment-binding-123",
    }


def start_response(
    *,
    bundle: str = READONLY_BUNDLE,
    scopes: list[str] | None = None,
    authorization_url: str | None = None,
) -> dict[str, object]:
    return {
        "handoff_id": "gwo_test123",
        "status": "pending",
        "authorization_url": authorization_url or direct_google_authorization_url(),
        "capability_bundle": bundle,
        "services": READONLY_SERVICES.copy(),
        "scopes": list(scopes or READONLY_SCOPES),
        "expires_at": "2030-01-01T00:00:00+00:00",
        "poll_after_ms": 2500,
    }


def disconnect_create_response() -> dict[str, object]:
    return {
        "schema": "tinyhat_google_workspace_disconnect_intent_v1",
        "intent_id": "gwd_test123",
        "owner_token": "disconnect-owner-token-value-1234567890",
        "status": "created",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "poll_after_ms": 1000,
    }


class DisconnectClient:
    def __init__(
        self,
        states: list[dict[str, object]] | None = None,
        *,
        binding: str = "assignment-binding-123",
        button_sent: bool = True,
        claim_status: str = "confirmed",
        deletion_claimed: bool = True,
    ) -> None:
        self.states = list(states or [])
        self.binding = binding
        self.button_sent = button_sent
        self.claim_status = claim_status
        self.deletion_claimed = deletion_claimed
        self.posts: list[tuple[str, dict[str, object]]] = []
        self.events: list[str] = []

    def get_json(self, path: str) -> dict[str, object]:
        self.events.append("binding")
        if not path.endswith("/assignment-binding"):
            raise AssertionError(f"Unexpected GET {path}")
        return {"tinyhat_assignment_binding": self.binding}

    def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        self.posts.append((path, payload))
        if path.endswith("/disconnect-intents"):
            self.events.append("create")
            return disconnect_create_response()
        if path.endswith("/activate"):
            self.events.append("activate")
            return {
                "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                "intent_id": "gwd_test123",
                "status": "offered",
                "button_sent": self.button_sent,
            }
        if path.endswith("/poll"):
            self.events.append("poll")
            if not self.states:
                raise AssertionError("Unexpected extra disconnect poll")
            return self.states.pop(0)
        if path.endswith("/claim"):
            self.events.append("claim")
            return {
                "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                "intent_id": "gwd_test123",
                "status": self.claim_status,
                "deletion_claimed": self.deletion_claimed,
            }
        if path.endswith("/complete"):
            self.events.append("complete")
            status = (
                "disconnected"
                if payload.get("outcome") == "disconnected"
                else str(payload.get("error_code") or "failed")
            )
            if status not in workspace.DISCONNECT_INTENT_STATUSES:
                status = "failed"
            return {
                "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                "intent_id": "gwd_test123",
                "status": status,
            }
        raise AssertionError(f"Unexpected POST {path}")


class FakeHermesContext:
    def __init__(self) -> None:
        self.tools: dict[str, dict] = {}
        self.skills: dict[str, Path] = {}

    def register_tool(self, **kwargs) -> None:
        self.tools[kwargs["name"]] = kwargs

    def register_skill(self, name: str, skill_md: Path) -> None:
        self.skills[name] = skill_md

    def register_command(self, *args, **kwargs) -> None:
        _ = (args, kwargs)

    def register_hook(self, *args, **kwargs) -> None:
        _ = (args, kwargs)


class PollingClient:
    def __init__(self, states: list[dict[str, object]], *, binding: str = "assignment-binding-123"):
        self.states = list(states)
        self.binding = binding
        self.gets: list[str] = []
        self.posts: list[tuple[str, dict[str, object]]] = []

    def get_json(self, path: str) -> dict[str, object]:
        self.gets.append(path)
        if path.endswith("/assignment-binding"):
            return {"tinyhat_assignment_binding": self.binding}
        if not self.states:
            raise AssertionError("Unexpected extra handoff poll")
        return self.states.pop(0)

    def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        self.posts.append((path, payload))
        return {}


class GoogleWorkspaceTests(unittest.TestCase):
    @contextlib.contextmanager
    def _patched_state(self, root: Path):
        state = root / "google-workspace"
        paths = {
            "STATE_DIR": state,
            "CREDENTIALS_PATH": state / "credentials.json",
            "HANDOFFS_DIR": state / "handoffs",
            "ACTIVE_HANDOFF_PATH": state / "active-handoff.json",
            "DISCONNECTS_DIR": state / "disconnects",
            "ACTIVE_DISCONNECT_PATH": state / "active-disconnect.json",
            "LIFECYCLE_LOCK_PATH": state / "lifecycle.lock",
        }
        with contextlib.ExitStack() as stack:
            for name, value in paths.items():
                stack.enter_context(mock.patch.object(workspace, name, value))
            stack.enter_context(
                mock.patch.object(workspace, "_context_assignment_check_cache", {})
            )
            yield

    def _worker_handoff(
        self,
        *,
        client: PollingClient,
        handoff_id: str = "gwo_test123",
        generation: str = "generation-value-that-is-long-enough-123",
        bundle: str = READONLY_BUNDLE,
        scopes: list[str] | None = None,
    ) -> workspace.GoogleWorkspaceWorkerHandoff:
        return workspace.GoogleWorkspaceWorkerHandoff(
            client=client,
            platform_auth="local_dev",
            handoff_id=handoff_id,
            owner_token=workspace._handoff_owner_token(generation),
            private_key_pem="private-key",
            expected_capability_bundle=bundle,
            expected_services=READONLY_SERVICES.copy(),
            expected_scopes=list(scopes or READONLY_SCOPES),
        )

    def _disconnect_intent(
        self,
        *,
        client: DisconnectClient,
        credentials: dict[str, object],
        intent_id: str = "gwd_test123",
        owner_token: str = "disconnect-owner-token-value-1234567890",
        expires_at: str | None = None,
    ) -> workspace.GoogleWorkspaceDisconnectIntent:
        normalized = workspace._normalize_saved_credentials(dict(credentials))
        generation = workspace._credential_generation(
            normalized,
            owner_token=owner_token,
        )
        return workspace.GoogleWorkspaceDisconnectIntent(
            client=client,
            platform_auth="local_dev",
            intent_id=intent_id,
            owner_token=owner_token,
            credential_generation=generation,
            expires_at=expires_at
            or (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            poll_after_ms=1000,
        )

    def _activate_disconnect_intent(
        self,
        intent: workspace.GoogleWorkspaceDisconnectIntent,
    ) -> None:
        workspace._write_active_disconnect_marker(
            intent_id=intent.intent_id,
            owner_token=intent.owner_token,
            credential_generation=intent.credential_generation,
        )

    @contextlib.contextmanager
    def _captured_notices(self):
        states: list[str] = []

        def capture(terminal_state: str) -> dict[str, bool]:
            states.append(terminal_state)
            return {"sent": True, "ok": True}

        with mock.patch.object(
            workspace,
            "_send_google_workspace_notice",
            side_effect=capture,
        ):
            yield states

    def _activate_handoff(
        self,
        *,
        handoff_id: str = "gwo_test123",
        generation: str = "generation-value-that-is-long-enough-123",
    ) -> str:
        owner_token = workspace._handoff_owner_token(generation)
        workspace._write_active_handoff_marker(
            handoff_id=handoff_id,
            owner_token=owner_token,
        )
        return owner_token

    def test_adapter_registers_google_workspace_tool_and_skill(self) -> None:
        ctx = FakeHermesContext()

        tinyhat.register(ctx)

        self.assertIn("tinyhat_google_workspace", ctx.tools)
        self.assertIs(ctx.tools["tinyhat_google_workspace"]["handler"], tools.google_workspace)
        self.assertEqual(
            ctx.tools["tinyhat_google_workspace"]["schema"],
            schemas.TINYHAT_GOOGLE_WORKSPACE_SCHEMA,
        )
        self.assertIn("tinyhat-google-workspace", ctx.skills)

    def test_schema_accepts_only_named_profiles_and_no_raw_scopes(self) -> None:
        schema = schemas.TINYHAT_GOOGLE_WORKSPACE_SCHEMA

        self.assertEqual(schema["required"], ["action"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["properties"]), {"action", "confirmed", "profile"})
        self.assertEqual(
            schema["properties"]["action"]["enum"],
            ["connect", "status", "disconnect"],
        )
        self.assertNotIn("scope", schema["properties"])
        self.assertNotIn("scopes", schema["properties"])
        self.assertEqual(
            schema["properties"]["profile"]["enum"],
            [
                "workspace_readonly",
                "gmail_send",
                "calendar_write",
                "gmail_send_calendar_write",
            ],
        )
        self.assertIn("read-only Gmail", schema["description"])
        self.assertIn("never trusts", schema["properties"]["action"]["description"])
        self.assertIn(
            "only through the tool-sent Telegram buttons",
            schema["properties"]["confirmed"]["description"],
        )

    def test_missing_and_invalid_actions_are_actionable(self) -> None:
        missing = json.loads(tools.google_workspace({}))
        invalid = json.loads(tools.google_workspace({"action": "refresh"}))

        self.assertEqual(missing["error"], "missing_required_parameter")
        self.assertEqual(missing["example_call"], {"action": "connect"})
        self.assertEqual(invalid["error"], "invalid_parameter")

    def test_gmail_send_upgrade_requires_confirmation_before_platform_call(self) -> None:
        with mock.patch.object(workspace, "build_platform_client") as build_client:
            result = json.loads(
                tools.google_workspace({"action": "connect", "profile": "gmail_send"})
            )

        self.assertEqual(result["error"], "confirmation_required")
        self.assertIn("gmail.send", result["message"])
        self.assertIn("separate from confirming any later email send", result["message"])
        self.assertIn("draft management is not enabled", result["message"])
        build_client.assert_not_called()

    def test_calendar_write_profiles_require_confirmation_before_platform_call(self) -> None:
        for profile in ("calendar_write", "gmail_send_calendar_write"):
            with (
                self.subTest(profile=profile),
                mock.patch.object(workspace, "build_platform_client") as build_client,
            ):
                result = json.loads(
                    tools.google_workspace({"action": "connect", "profile": profile})
                )

            self.assertEqual(result["error"], "confirmation_required")
            self.assertIn("Calendar events", result["message"])
            self.assertIn("calendar.events", result["message"])
            self.assertIn("separate from confirming", result["message"])
            build_client.assert_not_called()

    def test_calendar_write_profiles_are_fixed_additive_bundles(self) -> None:
        calendar = workspace.GOOGLE_PROFILE_CONFIGS["calendar_write"]
        combined = workspace.GOOGLE_PROFILE_CONFIGS["gmail_send_calendar_write"]

        self.assertEqual(calendar.capability_bundle, CALENDAR_WRITE_BUNDLE)
        self.assertEqual(list(calendar.scopes), CALENDAR_WRITE_SCOPES)
        self.assertEqual(
            combined.capability_bundle,
            GMAIL_SEND_CALENDAR_WRITE_BUNDLE,
        )
        self.assertEqual(
            list(combined.scopes),
            GMAIL_SEND_CALENDAR_WRITE_SCOPES,
        )
        self.assertEqual(
            combined.write_permissions,
            frozenset({"gmail_send", "calendar_events"}),
        )

    def test_confirmed_gmail_send_upgrade_requests_exact_allowlisted_superset(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object]]] = []

            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                self.calls.append((path, payload))
                return start_response(bundle=GMAIL_SEND_BUNDLE, scopes=GMAIL_SEND_SCOPES)

        client = FakeClient()
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace, "build_platform_client", return_value=(client, "local_dev")
            ),
            mock.patch.object(
                workspace,
                "_generate_key_pair",
                return_value=("one-time-private-key", "one-time-public-key"),
            ),
            mock.patch.object(workspace, "_start_worker_process") as start_worker,
            mock.patch.object(
                workspace,
                "_send_google_connect_button",
                return_value={"sent": True, "ok": True},
            ) as send_button,
        ):
            result = json.loads(
                tools.google_workspace(
                    {
                        "action": "connect",
                        "profile": "gmail_send",
                        "confirmed": True,
                    }
                )
            )

        self.assertEqual(result["status"], "waiting_for_user")
        self.assertEqual(result["profile"], "gmail_send")
        self.assertEqual(result["capability_bundle"], GMAIL_SEND_BUNDLE)
        self.assertIn("native Upgrade Google access button", result["message"])
        self.assertEqual(
            client.calls[0][1],
            {
                "public_key_pem": "one-time-public-key",
                "key_algorithm": workspace.KEY_ALGORITHM,
                "capability_bundle": GMAIL_SEND_BUNDLE,
                "requested_services": READONLY_SERVICES,
                "requested_scopes": GMAIL_SEND_SCOPES,
            },
        )
        start_worker.assert_called_once()
        self.assertEqual(
            start_worker.call_args.kwargs["handoff_metadata"],
            {
                "capability_bundle": GMAIL_SEND_BUNDLE,
                "services": READONLY_SERVICES,
                "scopes": GMAIL_SEND_SCOPES,
            },
        )
        send_button.assert_called_once_with(
            start_response()["authorization_url"], profile="gmail_send"
        )

    def test_calendar_write_upgrade_preserves_verified_gmail_send_permission(self) -> None:
        class UpgradeClient:
            def __init__(self) -> None:
                self.gets: list[str] = []
                self.posts: list[tuple[str, dict[str, object]]] = []

            def get_json(self, path: str) -> dict[str, object]:
                self.gets.append(path)
                return {"tinyhat_assignment_binding": "assignment-binding-123"}

            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                self.posts.append((path, payload))
                return start_response(
                    bundle=GMAIL_SEND_CALENDAR_WRITE_BUNDLE,
                    scopes=GMAIL_SEND_CALENDAR_WRITE_SCOPES,
                )

        client = UpgradeClient()
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace, "build_platform_client", return_value=(client, "local_dev")
            ),
            mock.patch.object(
                workspace,
                "_generate_key_pair",
                return_value=("one-time-private-key", "one-time-public-key"),
            ),
            mock.patch.object(workspace, "_start_worker_process") as start_worker,
            mock.patch.object(
                workspace,
                "_send_google_connect_button",
                return_value={"sent": True, "ok": True},
            ) as send_button,
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(
                    credential_envelope(
                        bundle=GMAIL_SEND_BUNDLE,
                        scopes=GMAIL_SEND_SCOPES,
                    )
                )
            )
            result = json.loads(
                tools.google_workspace(
                    {
                        "action": "connect",
                        "profile": "calendar_write",
                        "confirmed": True,
                    }
                )
            )

        self.assertEqual(result["profile"], "gmail_send_calendar_write")
        self.assertEqual(
            result["capability_bundle"],
            GMAIL_SEND_CALENDAR_WRITE_BUNDLE,
        )
        self.assertEqual(len(client.gets), 1)
        self.assertEqual(
            client.posts[0][1]["requested_scopes"],
            GMAIL_SEND_CALENDAR_WRITE_SCOPES,
        )
        self.assertEqual(
            start_worker.call_args.kwargs["handoff_metadata"]["scopes"],
            GMAIL_SEND_CALENDAR_WRITE_SCOPES,
        )
        send_button.assert_called_once_with(
            start_response()["authorization_url"],
            profile="gmail_send_calendar_write",
        )

    def test_default_reconnect_retains_verified_calendar_write_without_confirmation(self) -> None:
        class ReconnectClient:
            def get_json(self, _path: str) -> dict[str, object]:
                return {"tinyhat_assignment_binding": "assignment-binding-123"}

            def post_json(self, _path: str, _payload: dict[str, object]) -> dict[str, object]:
                return start_response(
                    bundle=CALENDAR_WRITE_BUNDLE,
                    scopes=CALENDAR_WRITE_SCOPES,
                )

        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                return_value=(ReconnectClient(), "local_dev"),
            ),
            mock.patch.object(
                workspace,
                "_generate_key_pair",
                return_value=("one-time-private-key", "one-time-public-key"),
            ),
            mock.patch.object(workspace, "_start_worker_process"),
            mock.patch.object(
                workspace,
                "_send_google_connect_button",
                return_value={"sent": True, "ok": True},
            ),
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(
                    credential_envelope(
                        bundle=CALENDAR_WRITE_BUNDLE,
                        scopes=CALENDAR_WRITE_SCOPES,
                    )
                )
            )
            result = json.loads(tools.google_workspace({"action": "connect"}))
            retained = json.loads(
                tools.google_workspace({"action": "connect", "profile": "calendar_write"})
            )

        self.assertNotIn("error", result)
        self.assertEqual(result["profile"], "calendar_write")
        self.assertEqual(result["capability_bundle"], CALENDAR_WRITE_BUNDLE)
        self.assertIn("native Upgrade Google access button", result["message"])
        self.assertNotIn("error", retained)
        self.assertEqual(retained["profile"], "calendar_write")

    def test_upgrade_does_not_preserve_write_permissions_from_stale_assignment(self) -> None:
        client = PollingClient([], binding="replacement-assignment-binding")
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(
                    credential_envelope(
                        bundle=GMAIL_SEND_BUNDLE,
                        scopes=GMAIL_SEND_SCOPES,
                    )
                )
            )
            with workspace._lifecycle_lock():
                resolved, resolved_client, platform_auth = (
                    workspace._resolve_profile_for_connection_locked(
                        workspace.GOOGLE_PROFILE_CONFIGS["calendar_write"],
                        confirmed=True,
                    )
                )

            self.assertEqual(resolved.name, "calendar_write")
            self.assertIs(resolved_client, client)
            self.assertEqual(platform_auth, "local_dev")
            self.assertFalse(workspace.CREDENTIALS_PATH.exists())

    def test_gmail_send_upgrade_preserves_verified_calendar_write_permission(self) -> None:
        client = PollingClient([])
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(
                    credential_envelope(
                        bundle=CALENDAR_WRITE_BUNDLE,
                        scopes=CALENDAR_WRITE_SCOPES,
                    )
                )
            )
            with workspace._lifecycle_lock():
                resolved, resolved_client, platform_auth = (
                    workspace._resolve_profile_for_connection_locked(
                        workspace.GOOGLE_PROFILE_CONFIGS["gmail_send"],
                        confirmed=True,
                    )
                )

        self.assertEqual(resolved.name, "gmail_send_calendar_write")
        self.assertIs(resolved_client, client)
        self.assertEqual(platform_auth, "local_dev")
        self.assertEqual(
            list(resolved.scopes),
            GMAIL_SEND_CALENDAR_WRITE_SCOPES,
        )

    def test_disconnect_winning_before_connect_resolution_cannot_bypass_confirmation(
        self,
    ) -> None:
        class Client:
            def __init__(self) -> None:
                self.posts: list[tuple[str, dict[str, object]]] = []

            def get_json(self, _path: str) -> dict[str, object]:
                return {"tinyhat_assignment_binding": "assignment-binding-123"}

            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                self.posts.append((path, payload))
                return start_response(bundle=GMAIL_SEND_BUNDLE, scopes=GMAIL_SEND_SCOPES)

        client = Client()
        real_start_connection = workspace._start_connection

        def disconnect_then_start(**kwargs):
            with workspace._lifecycle_lock():
                workspace._delete_credentials_locked()
            return real_start_connection(**kwargs)

        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ) as build_client,
            mock.patch.object(
                workspace,
                "_start_connection",
                side_effect=disconnect_then_start,
            ),
            mock.patch.object(workspace, "_start_worker_process") as start_worker,
            mock.patch.object(workspace, "_send_google_connect_button") as send_button,
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(
                    credential_envelope(
                        bundle=GMAIL_SEND_BUNDLE,
                        scopes=GMAIL_SEND_SCOPES,
                    )
                )
            )
            result = json.loads(
                tools.google_workspace({"action": "connect", "profile": "gmail_send"})
            )

        self.assertEqual(result["error"], "confirmation_required")
        self.assertEqual(client.posts, [])
        build_client.assert_not_called()
        start_worker.assert_not_called()
        send_button.assert_not_called()

    def test_stale_assignment_cleanup_cannot_bypass_write_confirmation(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.binding = "assignment-binding-123"
                self.posts: list[tuple[str, dict[str, object]]] = []

            def get_json(self, _path: str) -> dict[str, object]:
                return {"tinyhat_assignment_binding": self.binding}

            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                self.posts.append((path, payload))
                return start_response(bundle=GMAIL_SEND_BUNDLE, scopes=GMAIL_SEND_SCOPES)

        client = Client()
        real_start_connection = workspace._start_connection

        def assignment_changes_then_start(**kwargs):
            client.binding = "replacement-assignment-binding"
            return real_start_connection(**kwargs)

        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(
                workspace,
                "_start_connection",
                side_effect=assignment_changes_then_start,
            ),
            mock.patch.object(workspace, "_start_worker_process") as start_worker,
            mock.patch.object(workspace, "_send_google_connect_button") as send_button,
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(
                    credential_envelope(
                        bundle=GMAIL_SEND_BUNDLE,
                        scopes=GMAIL_SEND_SCOPES,
                    )
                )
            )
            result = json.loads(
                tools.google_workspace({"action": "connect", "profile": "gmail_send"})
            )

            self.assertEqual(result["error"], "confirmation_required")
            self.assertFalse(workspace.CREDENTIALS_PATH.exists())

        self.assertEqual(client.posts, [])
        start_worker.assert_not_called()
        send_button.assert_not_called()

    def test_profile_rejects_arbitrary_raw_scope_or_unknown_profile(self) -> None:
        with mock.patch.object(
            workspace,
            "_start_connection",
            return_value={"status": "waiting_for_user"},
        ) as start:
            raw = json.loads(
                tools.google_workspace(
                    {
                        "action": "connect",
                        "scopes": ["https://mail.google.com/"],
                    }
                )
            )
        unknown = json.loads(tools.google_workspace({"action": "connect", "profile": "gmail_full"}))

        # Hermes rejects additionalProperties before dispatch. Direct callers
        # still cannot influence the fixed default request.
        self.assertEqual(raw["status"], "waiting_for_user")
        self.assertEqual(
            start.call_args.kwargs["profile"].name,
            workspace.GOOGLE_WORKSPACE_PROFILE_READONLY,
        )
        self.assertEqual(unknown["error"], "invalid_parameter")

    def test_connect_sends_native_button_without_returning_authorization_url(self) -> None:
        class FakeClient:
            base_url = PLATFORM_BASE_URL

            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object]]] = []

            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                self.calls.append((path, payload))
                return start_response(authorization_url=prepare_authorization_url())

        client = FakeClient()
        worker_calls: list[dict[str, object]] = []
        button_urls: list[str] = []
        events: list[str] = []

        def start_worker(**kwargs) -> None:
            events.append("worker")
            worker_calls.append(kwargs)

        def send_button(url: str) -> dict[str, bool]:
            events.append("button")
            button_urls.append(url)
            return {"sent": True, "ok": True}

        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace, "build_platform_client", return_value=(client, "local_dev")
            ),
            mock.patch.object(
                workspace,
                "_generate_key_pair",
                return_value=("one-time-private-key", "one-time-public-key"),
            ),
            mock.patch.object(
                workspace,
                "_start_worker_process",
                side_effect=start_worker,
            ),
            mock.patch.object(
                workspace,
                "_send_google_connect_button",
                side_effect=send_button,
            ),
        ):
            result = json.loads(tools.google_workspace({"action": "connect"}))

        self.assertEqual(result["status"], "waiting_for_user")
        self.assertTrue(result["button_sent"])
        self.assertNotIn("authorization_url", result)
        self.assertNotIn("accounts.google.com", json.dumps(result))
        self.assertEqual(button_urls, [prepare_authorization_url()])
        self.assertEqual(events, ["worker", "button"])
        self.assertNotIn("handoff_id", result)
        self.assertNotIn("generation", result)
        self.assertEqual(len(client.calls), 1)
        request_payload = client.calls[0][1]
        self.assertEqual(
            request_payload,
            {
                "public_key_pem": "one-time-public-key",
                "key_algorithm": workspace.KEY_ALGORITHM,
                "capability_bundle": READONLY_BUNDLE,
                "requested_services": READONLY_SERVICES,
                "requested_scopes": READONLY_SCOPES,
            },
        )
        self.assertNotIn("client_id", request_payload)
        self.assertNotIn("client_secret", request_payload)
        self.assertEqual(worker_calls[0]["private_key_pem"], "one-time-private-key")
        self.assertEqual(
            worker_calls[0]["handoff_metadata"],
            {
                "capability_bundle": READONLY_BUNDLE,
                "services": READONLY_SERVICES,
                "scopes": READONLY_SCOPES,
            },
        )

    def test_connect_button_failure_is_safe_after_worker_start(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object]]] = []

            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                self.calls.append((path, payload))
                return start_response() if len(self.calls) == 1 else {}

        client = FakeClient()
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(
                workspace,
                "_generate_key_pair",
                return_value=("one-time-private-key", "one-time-public-key"),
            ),
            mock.patch.object(
                workspace,
                "_send_google_connect_button",
                return_value={"sent": False, "ok": False},
            ),
            mock.patch.object(workspace, "_start_worker_process") as start_worker,
        ):
            result = json.loads(tools.google_workspace({"action": "connect"}))

        self.assertEqual(result["status"], "failed")
        self.assertNotIn("authorization_url", result)
        self.assertNotIn("accounts.google.com", json.dumps(result))
        start_worker.assert_called_once()
        self.assertEqual(
            client.calls[-1][1],
            {
                "installed": False,
                "message": "Connect Google button could not be delivered.",
            },
        )

    def test_worker_start_failure_sends_no_dead_button(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object]]] = []

            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                self.calls.append((path, payload))
                return start_response() if len(self.calls) == 1 else {}

        client = FakeClient()
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(
                workspace,
                "_generate_key_pair",
                return_value=("one-time-private-key", "one-time-public-key"),
            ),
            mock.patch.object(
                workspace,
                "_start_worker_process",
                side_effect=workspace.GoogleWorkspaceError("worker failed"),
            ),
            mock.patch.object(workspace, "_send_google_connect_button") as send_button,
        ):
            result = json.loads(tools.google_workspace({"action": "connect"}))

        self.assertEqual(result["status"], "failed")
        self.assertNotIn("authorization_url", result)
        send_button.assert_not_called()
        self.assertEqual(
            client.calls[-1][1],
            {
                "installed": False,
                "message": "Google sign-in worker could not start.",
            },
        )

    def test_button_failure_claim_allows_worker_to_clean_one_time_state(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.status = "pending"
                self.calls: list[tuple[str, dict[str, object]]] = []

            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                self.calls.append((path, payload))
                if len(self.calls) == 1:
                    return start_response()
                self.status = "claimed"
                return {}

            def get_json(self, _path: str) -> dict[str, object]:
                return {"status": self.status}

        client = FakeClient()
        worker_threads: list[threading.Thread] = []

        def start_worker(**kwargs) -> None:
            handoff_id = str(kwargs["handoff"]["handoff_id"])
            generation = str(kwargs["generation"])
            key_path = workspace._write_worker_state(
                handoff_id=handoff_id,
                private_key_pem=str(kwargs["private_key_pem"]),
                generation=generation,
                handoff_metadata=kwargs["handoff_metadata"],
            )
            workspace._write_active_handoff_marker(
                handoff_id=handoff_id,
                owner_token=workspace._handoff_owner_token(generation),
            )
            worker = threading.Thread(
                target=google_workspace_worker.run_worker,
                kwargs={"handoff_id": handoff_id, "key_path": key_path},
                daemon=True,
            )
            worker.start()
            worker_threads.append(worker)

        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(
                google_workspace_worker,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(
                workspace,
                "_generate_key_pair",
                return_value=("one-time-private-key", "one-time-public-key"),
            ),
            mock.patch.object(workspace, "_start_worker_process", side_effect=start_worker),
            mock.patch.object(
                workspace,
                "_send_google_connect_button",
                return_value={"sent": False, "ok": False},
            ),
        ):
            result = json.loads(tools.google_workspace({"action": "connect"}))
            for worker in worker_threads:
                worker.join(timeout=2)

            self.assertEqual(result["status"], "failed")
            self.assertTrue(worker_threads)
            self.assertFalse(worker_threads[0].is_alive())
            self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())
            self.assertEqual(list(workspace.HANDOFFS_DIR.iterdir()), [])

    def test_connect_button_uses_native_inline_keyboard(self) -> None:
        sends: list[dict[str, object]] = []
        authorization_url = str(start_response()["authorization_url"])
        with (
            mock.patch.object(
                tools,
                "_telegram_credentials",
                return_value=("telegram-token", "chat-123"),
            ),
            mock.patch.object(
                tools,
                "_telegram_send_message",
                side_effect=lambda **kwargs: sends.append(kwargs) or {"ok": True},
            ),
        ):
            result = workspace._send_google_connect_button(authorization_url)

        self.assertEqual(result, {"sent": True, "ok": True})
        self.assertEqual(len(sends), 1)
        self.assertEqual(
            sends[0]["reply_markup"],
            {"inline_keyboard": [[{"text": "Connect Google", "url": authorization_url}]]},
        )
        self.assertNotIn(authorization_url, str(sends[0]["text"]))

    def test_gmail_send_upgrade_button_is_distinct_from_first_connect(self) -> None:
        sends: list[dict[str, object]] = []
        authorization_url = str(start_response()["authorization_url"])
        with (
            mock.patch.object(
                tools,
                "_telegram_credentials",
                return_value=("telegram-token", "chat-123"),
            ),
            mock.patch.object(
                tools,
                "_telegram_send_message",
                side_effect=lambda **kwargs: sends.append(kwargs) or {"ok": True},
            ),
        ):
            result = workspace._send_google_connect_button(
                authorization_url,
                profile="gmail_send",
            )

        self.assertEqual(result, {"sent": True, "ok": True})
        self.assertEqual(len(sends), 1)
        self.assertEqual(
            sends[0]["reply_markup"],
            {
                "inline_keyboard": [
                    [{"text": "Upgrade Google access", "url": authorization_url}]
                ]
            },
        )
        self.assertIn("Upgrade Google Workspace", str(sends[0]["text"]))
        self.assertNotIn(authorization_url, str(sends[0]["text"]))

    def test_telegram_message_helper_encodes_reply_markup_as_json(self) -> None:
        captured: dict[str, object] = {}

        def post(**kwargs) -> dict[str, bool]:
            captured.update(kwargs)
            return {"ok": True}

        reply_markup = {
            "inline_keyboard": [[{"text": "Connect Google", "url": "https://example.test"}]]
        }
        with mock.patch.object(tools, "_telegram_post", side_effect=post):
            tools._telegram_send_message(
                token="telegram-token",
                chat_id="chat-123",
                text="Connect",
                reply_markup=reply_markup,
            )

        form = parse.parse_qs(bytes(captured["body"]).decode("utf-8"))
        self.assertEqual(json.loads(form["reply_markup"][0]), reply_markup)

    def test_authorization_url_accepts_tinyhat_prepare_and_legacy_google(self) -> None:
        prepare_url = prepare_authorization_url()
        self.assertEqual(
            workspace._validated_authorization_url(
                prepare_url,
                platform_base_url=PLATFORM_BASE_URL,
            ),
            prepare_url,
        )

        direct_google_url = direct_google_authorization_url()
        self.assertEqual(
            workspace._validated_authorization_url(direct_google_url),
            direct_google_url,
        )

    def test_authorization_url_rejects_untrusted_prepare_shapes(self) -> None:
        ticket = f"gwol1.1.{'a' * 64}"
        invalid_urls = (
            f"https://evil.example{PREPARE_PATH}#{ticket}",
            f"http://api.example.test{PREPARE_PATH}#{ticket}",
            f"https://user@api.example.test{PREPARE_PATH}#{ticket}",
            f"{PLATFORM_BASE_URL}/wrong-path#{ticket}",
            f"{PLATFORM_BASE_URL}{PREPARE_PATH}?ticket=visible#{ticket}",
            f"{PLATFORM_BASE_URL}{PREPARE_PATH}",
            f"{PLATFORM_BASE_URL}{PREPARE_PATH}#gwol1.0.{'a' * 64}",
            f"{PLATFORM_BASE_URL}{PREPARE_PATH}#gwol1.1.too-short",
            f"{PLATFORM_BASE_URL}{PREPARE_PATH}#gwol1.1.{'a' * 16001}",
        )
        for authorization_url in invalid_urls:
            with (
                self.subTest(authorization_url=authorization_url[:120]),
                self.assertRaises(workspace.GoogleWorkspaceError),
            ):
                workspace._validated_authorization_url(
                    authorization_url,
                    platform_base_url=PLATFORM_BASE_URL,
                )

        with self.assertRaises(workspace.GoogleWorkspaceError):
            workspace._validated_authorization_url(
                f"https://{PREPARE_PATH}#{ticket}",
                platform_base_url="https://",
            )

    def test_connect_rejects_platform_url_or_capability_drift(self) -> None:
        variants = []
        bad_url = start_response()
        bad_url["authorization_url"] = "https://evil.example/oauth?state=x"
        variants.append(bad_url)
        bad_bundle = start_response()
        bad_bundle["capability_bundle"] = "gmail_full_access"
        variants.append(bad_bundle)
        bad_services = start_response()
        bad_services["services"] = ["identity", "gmail"]
        variants.append(bad_services)
        bad_scopes = start_response()
        bad_scopes["scopes"] = [
            *READONLY_SCOPES,
            "https://www.googleapis.com/auth/drive.file",
        ]
        variants.append(bad_scopes)
        reordered_scopes = start_response()
        reordered_scopes["scopes"] = list(reversed(READONLY_SCOPES))
        variants.append(reordered_scopes)

        class FakeClient:
            def __init__(self, response: dict[str, object]) -> None:
                self.response = response

            def post_json(self, *_args, **_kwargs) -> dict[str, object]:
                return self.response

        for response in variants:
            with (
                self.subTest(response=response),
                tempfile.TemporaryDirectory() as tmp,
                self._patched_state(Path(tmp)),
                mock.patch.object(
                    workspace,
                    "build_platform_client",
                    return_value=(FakeClient(response), "local_dev"),
                ),
                mock.patch.object(
                    workspace,
                    "_generate_key_pair",
                    return_value=("private", "public"),
                ),
                self.assertRaises(workspace.GoogleWorkspaceError),
            ):
                workspace._start_connection()

    def test_worker_state_is_owner_only_and_has_no_oauth_client_or_pkce(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
        ):
            key_path = workspace._write_worker_state(
                handoff_id="gwo_private123",
                private_key_pem="private-key",
                generation="generation-value-that-is-long-enough-123",
                handoff_metadata={
                    "capability_bundle": READONLY_BUNDLE,
                    "services": READONLY_SERVICES,
                    "scopes": READONLY_SCOPES,
                },
            )
            directory = key_path.parent
            generation_path = directory / "generation"
            metadata_path = directory / "handoff-metadata.json"

            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            for path in (key_path, generation_path, metadata_path):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            all_text = " ".join(path.read_text() for path in directory.iterdir())
            self.assertNotIn("client_secret", all_text)
            self.assertNotIn("pkce", all_text.lower())
            self.assertNotIn("code_verifier", all_text)

    def test_credential_envelope_is_normalized_and_saved_privately(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
        ):
            normalized = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(normalized)
            saved = json.loads(workspace.CREDENTIALS_PATH.read_text())

            self.assertEqual(saved["capability_bundle"], READONLY_BUNDLE)
            self.assertEqual(saved["services"], READONLY_SERVICES)
            self.assertEqual(saved["scopes"], READONLY_SCOPES)
            self.assertIn("connected_at", saved)
            self.assertEqual(stat.S_IMODE(workspace.STATE_DIR.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(workspace.CREDENTIALS_PATH.stat().st_mode), 0o600)

    def test_credential_envelope_rejects_secret_and_capability_drift(self) -> None:
        variants = []
        with_secret = credential_envelope()
        with_secret["client_secret"] = "server-secret"
        variants.append(with_secret)
        bad_bundle = credential_envelope()
        bad_bundle["capability_bundle"] = "gmail_full_access"
        variants.append(bad_bundle)
        bad_services = credential_envelope()
        bad_services["services"] = ["identity", "gmail"]
        variants.append(bad_services)
        duplicate_scopes = credential_envelope()
        duplicate_scopes["scopes"] = [*READONLY_SCOPES, READONLY_SCOPES[-1]]
        variants.append(duplicate_scopes)
        reordered_services = credential_envelope()
        reordered_services["services"] = list(reversed(READONLY_SERVICES))
        variants.append(reordered_services)
        unverified = credential_envelope()
        unverified["email_verified"] = False
        variants.append(unverified)
        with_code = credential_envelope()
        with_code["authorization_code"] = "must-not-cross-the-boundary"
        variants.append(with_code)
        wrong_token_type = credential_envelope()
        wrong_token_type["token_type"] = "MAC"
        variants.append(wrong_token_type)

        for value in variants:
            with self.subTest(value=value), self.assertRaises(workspace.GoogleWorkspaceError):
                workspace._normalize_credentials(value)

    def test_status_wipes_malformed_owner_only_credentials_and_pending_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            key_path = workspace._write_worker_state(
                handoff_id="gwo_stale123",
                private_key_pem="stale-private-key",
                generation="stale-generation-value-that-is-long-enough",
                handoff_metadata={
                    "capability_bundle": READONLY_BUNDLE,
                    "services": READONLY_SERVICES,
                    "scopes": READONLY_SCOPES,
                },
            )
            workspace._write_active_handoff_marker(
                handoff_id="gwo_stale123",
                owner_token="stale-owner-token",
            )
            workspace._write_private_file(
                workspace.CREDENTIALS_PATH,
                '{"access_token":"stale-token-without-closing-json"',
            )
            workspace.CREDENTIALS_PATH.chmod(0o640)

            result = workspace._status_payload()

            self.assertEqual(result["status"], "invalid")
            self.assertFalse(workspace.CREDENTIALS_PATH.exists())
            self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())
            self.assertFalse(key_path.parent.exists())
            self.assertFalse(workspace.HANDOFFS_DIR.exists())

    def test_connect_wipes_malformed_credentials_before_starting_fresh_handoff(self) -> None:
        class FakeClient:
            def post_json(self, _path: str, _payload: dict[str, object]) -> dict[str, object]:
                return start_response()

        worker_calls: list[dict[str, object]] = []
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                return_value=(FakeClient(), "local_dev"),
            ),
            mock.patch.object(
                workspace,
                "_generate_key_pair",
                return_value=("fresh-private-key", "fresh-public-key"),
            ),
            mock.patch.object(
                workspace,
                "_send_google_connect_button",
                return_value={"sent": True, "ok": True},
            ),
            mock.patch.object(
                workspace,
                "_start_worker_process",
                side_effect=lambda **kwargs: worker_calls.append(kwargs),
            ),
        ):
            stale_key = workspace._write_worker_state(
                handoff_id="gwo_stalereconnect123",
                private_key_pem="stale-private-key",
                generation="stale-generation-value-that-is-long-enough",
                handoff_metadata={
                    "capability_bundle": READONLY_BUNDLE,
                    "services": READONLY_SERVICES,
                    "scopes": READONLY_SCOPES,
                },
            )
            workspace._write_active_handoff_marker(
                handoff_id="gwo_stalereconnect123",
                owner_token="stale-owner-token",
            )
            workspace._write_private_file(
                workspace.CREDENTIALS_PATH,
                '{"refresh_token":"stale-refresh-without-closing-json"',
            )

            result = workspace._start_connection()

            self.assertTrue(result["button_sent"])
            self.assertFalse(workspace.CREDENTIALS_PATH.exists())
            self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())
            self.assertFalse(stale_key.parent.exists())
            self.assertFalse(workspace.HANDOFFS_DIR.exists())
            self.assertEqual(len(worker_calls), 1)

    def test_active_marker_and_lock_are_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            workspace._write_active_handoff_marker(
                handoff_id="gwo_modes123",
                owner_token="owner-token",
            )
            with workspace._lifecycle_lock():
                pass

            self.assertEqual(stat.S_IMODE(workspace.ACTIVE_HANDOFF_PATH.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(workspace.LIFECYCLE_LOCK_PATH.stat().st_mode), 0o600)

    def test_older_worker_cannot_install_after_new_connect_marker(self) -> None:
        client = PollingClient([])
        old = self._worker_handoff(client=client, generation="old-generation-value-123456789012345")
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            self._captured_notices() as notices,
        ):
            self._activate_handoff(generation="new-generation-value-123456789012345")
            with mock.patch.object(
                workspace,
                "_decrypt_ciphertext",
                side_effect=AssertionError("superseded worker must not decrypt"),
            ):
                workspace._poll_and_install(old)

            self.assertFalse(workspace.CREDENTIALS_PATH.exists())
            self.assertEqual(client.posts[-1][1]["installed"], False)
            self.assertEqual(
                client.posts[-1][1]["message"],
                workspace.TERMINAL_HANDOFF_MESSAGES["superseded"],
            )
            self.assertEqual(notices, ["superseded"])

    def test_ready_worker_saves_claims_clears_then_notifies(self) -> None:
        events: list[str] = []
        notice_states: list[str] = []

        class EventClient(PollingClient):
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                self_test.assertTrue(workspace.ACTIVE_HANDOFF_PATH.exists())
                events.append("claim")
                return super().post_json(path, payload)

        self_test = self
        client = EventClient(
            [
                {
                    "status": "ready",
                    "terminal_state": "ready",
                    "ciphertext_payload": {"ciphertext": "opaque"},
                }
            ]
        )
        handoff = self._worker_handoff(client=client)
        original_save = workspace._atomic_save_credentials
        original_clear = workspace._clear_active_handoff

        def save(credentials: dict[str, object]) -> None:
            events.append("save")
            original_save(credentials)

        def send_notice(terminal_state: str) -> dict[str, bool]:
            events.append("notice")
            notice_states.append(terminal_state)
            return {"sent": True, "ok": True}

        def clear_active(current_handoff: workspace.GoogleWorkspaceWorkerHandoff) -> None:
            events.append("clear")
            original_clear(current_handoff)

        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "_decrypt_ciphertext",
                return_value=json.dumps(credential_envelope()),
            ),
            mock.patch.object(workspace, "_atomic_save_credentials", side_effect=save),
            mock.patch.object(
                workspace,
                "_clear_active_handoff",
                side_effect=clear_active,
            ),
            mock.patch.object(
                workspace,
                "_send_google_workspace_notice",
                side_effect=send_notice,
            ),
        ):
            self._activate_handoff()
            workspace._poll_and_install(handoff)
            saved = json.loads(workspace.CREDENTIALS_PATH.read_text())

        self.assertEqual(events, ["save", "claim", "clear", "notice"])
        self.assertEqual(notice_states, ["ready"])
        self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())
        self.assertEqual(saved["email"], "owner@example.com")
        claim = client.posts[-1][1]
        self.assertEqual(claim, {"installed": True, "message": None})
        self.assertNotIn("access_token", json.dumps(claim))
        self.assertNotIn("refresh_token", json.dumps(claim))

    def test_ready_worker_retries_claim_before_clearing_or_notifying(self) -> None:
        claim_attempts: list[int] = []

        class FlakyClaimClient(PollingClient):
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                claim_attempts.append(len(claim_attempts) + 1)
                if len(claim_attempts) < workspace.INSTALL_CLAIM_MAX_ATTEMPTS:
                    raise RuntimeError("temporary platform failure")
                return super().post_json(path, payload)

        client = FlakyClaimClient(
            [
                {
                    "status": "ready",
                    "terminal_state": "ready",
                    "ciphertext_payload": {"ciphertext": "opaque"},
                }
            ]
        )
        handoff = self._worker_handoff(client=client)
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "_decrypt_ciphertext",
                return_value=json.dumps(credential_envelope()),
            ),
            mock.patch.object(workspace.time, "sleep") as sleep,
            self._captured_notices() as notices,
        ):
            self._activate_handoff()
            workspace._poll_and_install(handoff)

            self.assertEqual(
                claim_attempts,
                list(range(1, workspace.INSTALL_CLAIM_MAX_ATTEMPTS + 1)),
            )
            self.assertEqual(sleep.call_count, workspace.INSTALL_CLAIM_MAX_ATTEMPTS - 1)
            self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())
            self.assertEqual(notices, ["ready"])

    def test_ready_worker_claim_failure_keeps_marker_and_sends_no_success(self) -> None:
        claim_attempts = 0

        class FailingClaimClient(PollingClient):
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                nonlocal claim_attempts
                claim_attempts += 1
                if not workspace.ACTIVE_HANDOFF_PATH.exists():
                    raise AssertionError("claim retry lost the active handoff marker")
                raise RuntimeError("platform unavailable")

        client = FailingClaimClient(
            [
                {
                    "status": "ready",
                    "terminal_state": "ready",
                    "ciphertext_payload": {"ciphertext": "opaque"},
                }
            ]
        )
        handoff = self._worker_handoff(client=client)
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "_decrypt_ciphertext",
                return_value=json.dumps(credential_envelope()),
            ),
            mock.patch.object(workspace.time, "sleep"),
            self._captured_notices() as notices,
        ):
            self._activate_handoff()
            with self.assertRaisesRegex(RuntimeError, "platform unavailable"):
                workspace._poll_and_install(handoff)

            self.assertEqual(claim_attempts, workspace.INSTALL_CLAIM_MAX_ATTEMPTS)
            self.assertTrue(workspace.CREDENTIALS_PATH.exists())
            self.assertTrue(workspace.ACTIVE_HANDOFF_PATH.exists())
            self.assertEqual(notices, [])

    def test_cancelled_gmail_send_upgrade_keeps_existing_readonly_credential(self) -> None:
        client = PollingClient([{"terminal_state": "cancelled"}])
        handoff = self._worker_handoff(
            client=client,
            bundle=GMAIL_SEND_BUNDLE,
            scopes=GMAIL_SEND_SCOPES,
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            self._captured_notices() as notices,
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(credential_envelope())
            )
            self._activate_handoff()
            workspace._poll_and_install(handoff)
            saved = json.loads(workspace.CREDENTIALS_PATH.read_text())

        self.assertEqual(saved["capability_bundle"], READONLY_BUNDLE)
        self.assertEqual(saved["scopes"], READONLY_SCOPES)
        self.assertEqual(notices, ["cancelled"])

    def test_successful_gmail_send_upgrade_atomically_replaces_connection(self) -> None:
        client = PollingClient(
            [
                {
                    "terminal_state": "ready",
                    "ciphertext_payload": {"ciphertext": "opaque"},
                }
            ]
        )
        handoff = self._worker_handoff(
            client=client,
            bundle=GMAIL_SEND_BUNDLE,
            scopes=GMAIL_SEND_SCOPES,
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            self._captured_notices() as notices,
            mock.patch.object(
                workspace,
                "_decrypt_ciphertext",
                return_value=json.dumps(
                    credential_envelope(
                        bundle=GMAIL_SEND_BUNDLE,
                        scopes=GMAIL_SEND_SCOPES,
                    )
                ),
            ),
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(credential_envelope())
            )
            self._activate_handoff()
            workspace._poll_and_install(handoff)
            saved = json.loads(workspace.CREDENTIALS_PATH.read_text())

        self.assertEqual(saved["capability_bundle"], GMAIL_SEND_BUNDLE)
        self.assertEqual(saved["scopes"], GMAIL_SEND_SCOPES)
        self.assertEqual(notices, ["ready_gmail_send"])
        self.assertEqual(client.posts[-1][1], {"installed": True, "message": None})

    def test_successful_combined_upgrade_reports_both_write_permissions(self) -> None:
        client = PollingClient(
            [{"terminal_state": "ready", "ciphertext_payload": {"ciphertext": "opaque"}}]
        )
        handoff = self._worker_handoff(
            client=client,
            bundle=GMAIL_SEND_CALENDAR_WRITE_BUNDLE,
            scopes=GMAIL_SEND_CALENDAR_WRITE_SCOPES,
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            self._captured_notices() as notices,
            mock.patch.object(
                workspace,
                "_decrypt_ciphertext",
                return_value=json.dumps(
                    credential_envelope(
                        bundle=GMAIL_SEND_CALENDAR_WRITE_BUNDLE,
                        scopes=GMAIL_SEND_CALENDAR_WRITE_SCOPES,
                    )
                ),
            ),
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(
                    credential_envelope(
                        bundle=GMAIL_SEND_BUNDLE,
                        scopes=GMAIL_SEND_SCOPES,
                    )
                )
            )
            self._activate_handoff()
            workspace._poll_and_install(handoff)
            saved = json.loads(workspace.CREDENTIALS_PATH.read_text())

        self.assertEqual(
            saved["capability_bundle"],
            GMAIL_SEND_CALENDAR_WRITE_BUNDLE,
        )
        self.assertEqual(saved["scopes"], GMAIL_SEND_CALENDAR_WRITE_SCOPES)
        self.assertEqual(notices, ["ready_gmail_send_calendar_write"])
        self.assertIn(
            "Calendar event changes",
            workspace.TELEGRAM_NOTICE_MESSAGES["ready_gmail_send_calendar_write"],
        )

    def test_terminal_states_stop_with_fixed_safe_messages(self) -> None:
        for terminal_state, expected_message in workspace.TERMINAL_HANDOFF_MESSAGES.items():
            with self.subTest(terminal_state=terminal_state), tempfile.TemporaryDirectory() as tmp:
                client = PollingClient(
                    [{"status": terminal_state, "terminal_state": terminal_state}]
                )
                handoff = self._worker_handoff(client=client)
                with (
                    self._patched_state(Path(tmp)),
                    self._captured_notices() as notices,
                ):
                    self._activate_handoff()
                    with mock.patch.object(
                        workspace,
                        "_decrypt_ciphertext",
                        side_effect=AssertionError("terminal state must not decrypt"),
                    ):
                        workspace._poll_and_install(handoff)

                    self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())
                    self.assertEqual(
                        client.posts[-1][1],
                        {"installed": False, "message": expected_message},
                    )
                    self.assertEqual(notices, [terminal_state])
                    notice_text = workspace.TELEGRAM_NOTICE_MESSAGES[terminal_state]
                    self.assertNotIn("test-access-value", notice_text)
                    self.assertNotIn("test-refresh-value", notice_text)

    def test_telegram_notices_use_fixed_text_without_credential_leakage(self) -> None:
        sent_texts: list[str] = []

        def send_message(**kwargs) -> dict[str, bool]:
            sent_texts.append(kwargs["text"])
            return {"ok": True}

        states = [
            "ready",
            "ready_gmail_send",
            "ready_calendar_write",
            "ready_gmail_send_calendar_write",
            *workspace.TERMINAL_HANDOFF_MESSAGES,
        ]
        with (
            mock.patch.object(
                tools,
                "_telegram_credentials",
                return_value=("telegram-bot-secret", "chat-123"),
            ),
            mock.patch.object(
                tools,
                "_telegram_send_message",
                side_effect=send_message,
            ),
        ):
            results = [workspace._send_google_workspace_notice(state) for state in states]

        self.assertTrue(all(result == {"sent": True, "ok": True} for result in results))
        self.assertEqual(
            sent_texts,
            [workspace.TELEGRAM_NOTICE_MESSAGES[state] for state in states],
        )
        serialized = "\n".join(sent_texts)
        for forbidden in (
            "telegram-bot-secret",
            "test-access-value",
            "test-refresh-value",
            "central-public-client.apps.googleusercontent.com",
            "assignment-binding-123",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_notification_failure_does_not_prevent_ready_install_or_claim(self) -> None:
        client = PollingClient(
            [{"terminal_state": "ready", "ciphertext_payload": {"ciphertext": "opaque"}}]
        )
        handoff = self._worker_handoff(client=client)
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "_decrypt_ciphertext",
                return_value=json.dumps(credential_envelope()),
            ),
            mock.patch.object(
                tools,
                "_telegram_credentials",
                side_effect=RuntimeError("telegram unavailable"),
            ),
        ):
            self._activate_handoff()
            workspace._poll_and_install(handoff)

            self.assertTrue(workspace.CREDENTIALS_PATH.exists())
            self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())
            self.assertEqual(client.posts[-1][1], {"installed": True, "message": None})

    def test_notification_failure_does_not_prevent_terminal_claim(self) -> None:
        client = PollingClient([{"terminal_state": "expired"}])
        handoff = self._worker_handoff(client=client)
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                tools,
                "_telegram_credentials",
                side_effect=RuntimeError("telegram unavailable"),
            ),
        ):
            self._activate_handoff()
            workspace._poll_and_install(handoff)

            self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())
            self.assertEqual(
                client.posts[-1][1],
                {
                    "installed": False,
                    "message": workspace.TERMINAL_HANDOFF_MESSAGES["expired"],
                },
            )

    def test_ready_worker_revalidates_assignment_before_install(self) -> None:
        client = PollingClient(
            [{"terminal_state": "ready", "ciphertext_payload": {"ciphertext": "opaque"}}],
            binding="different-assignment",
        )
        handoff = self._worker_handoff(client=client)
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "_decrypt_ciphertext",
                return_value=json.dumps(credential_envelope()),
            ),
            self._captured_notices() as notices,
        ):
            self._activate_handoff()
            workspace._poll_and_install(handoff)

            self.assertFalse(workspace.CREDENTIALS_PATH.exists())
            self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())
            self.assertEqual(client.posts[-1][1]["installed"], False)
            self.assertIn("assignment changed", str(client.posts[-1][1]["message"]).lower())
            self.assertEqual(notices, ["failed"])

    def test_status_returns_metadata_without_tokens_or_local_path(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                return_value=(PollingClient([]), "local_dev"),
            ),
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(credential_envelope())
            )
            result = workspace._status_payload()

        self.assertTrue(result["connected"])
        self.assertEqual(result["email"], "owner@example.com")
        serialized = json.dumps(result)
        self.assertNotIn("test-access-value", serialized)
        self.assertNotIn("test-refresh-value", serialized)
        self.assertNotIn("credentials.json", serialized)

    def test_status_wipes_credentials_on_assignment_change(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                return_value=(PollingClient([], binding="new-assignment"), "local_dev"),
            ),
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(credential_envelope())
            )
            result = workspace._status_payload()

            self.assertFalse(result["connected"])
            self.assertFalse(workspace.CREDENTIALS_PATH.exists())

    def test_stale_binding_reread_race_wipes_newly_malformed_file_and_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(credential_envelope())
            )
            stale_key = workspace._write_worker_state(
                handoff_id="gwo_bindingrace123",
                private_key_pem="stale-private-key",
                generation="stale-generation-value-that-is-long-enough",
                handoff_metadata={
                    "capability_bundle": READONLY_BUNDLE,
                    "services": READONLY_SERVICES,
                    "scopes": READONLY_SCOPES,
                },
            )
            workspace._write_active_handoff_marker(
                handoff_id="gwo_bindingrace123",
                owner_token="stale-owner-token",
            )
            original_read = workspace._read_credentials
            read_count = 0
            locked_reread_call = 2

            def racing_read():
                nonlocal read_count
                read_count += 1
                if read_count == locked_reread_call:
                    workspace.CREDENTIALS_PATH.write_text(
                        '{"refresh_token":"became-malformed-during-reread"',
                        encoding="utf-8",
                    )
                    workspace.CREDENTIALS_PATH.chmod(0o600)
                return original_read()

            with (
                mock.patch.object(workspace, "_read_credentials", side_effect=racing_read),
                mock.patch.object(
                    workspace,
                    "build_platform_client",
                    return_value=(
                        PollingClient([], binding="different-assignment"),
                        "local_dev",
                    ),
                ),
            ):
                result = workspace.remove_credentials_if_assignment_changed()

            self.assertEqual(result, "invalid")
            self.assertGreaterEqual(read_count, 3)
            self.assertFalse(workspace.CREDENTIALS_PATH.exists())
            self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())
            self.assertFalse(stale_key.parent.exists())
            self.assertFalse(workspace.HANDOFFS_DIR.exists())

    def test_status_fails_closed_but_keeps_file_when_platform_is_unreachable(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                side_effect=workspace.GoogleWorkspaceError("offline"),
            ),
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(credential_envelope())
            )
            result = workspace._status_payload()

            self.assertEqual(result["status"], "verification_unavailable")
            self.assertFalse(result["connected"])
            self.assertTrue(workspace.CREDENTIALS_PATH.exists())

    def test_not_connected_status_requires_a_fresh_connect_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            result = workspace._status_payload()

        self.assertEqual(result["status"], "not_connected")
        self.assertFalse(result["connected"])
        self.assertTrue(result["connect_required"])
        self.assertEqual(
            result["recommended_tool_call"],
            {
                "tool": "tinyhat_google_workspace",
                "arguments": {"action": "connect"},
            },
        )
        self.assertIn("call tinyhat_google_workspace with action='connect' now", result["message"])
        self.assertIn("Do not reuse", result["message"])

    def test_pre_llm_hook_checks_assignment_before_context(self) -> None:
        with mock.patch.object(
            tinyhat_context,
            "remove_credentials_if_assignment_changed_for_context",
            return_value="not_present",
        ) as cleanup:
            result = tinyhat_context.inject_tinyhat_context(
                user_message="connect google",
                is_first_turn=False,
            )

        cleanup.assert_called_once_with()
        self.assertIn("existing Google account", result["context"])
        self.assertIn("read-only Gmail, Calendar, and Drive", result["context"])

    def test_irrelevant_pre_llm_turn_skips_assignment_network_check(self) -> None:
        with mock.patch.object(
            tinyhat_context,
            "remove_credentials_if_assignment_changed_for_context",
        ) as cleanup:
            result = tinyhat_context.inject_tinyhat_context(
                user_message="What is two plus two?",
                is_first_turn=False,
            )

        self.assertIsNone(result)
        cleanup.assert_not_called()

    def test_context_assignment_match_is_briefly_cached_but_use_is_not(self) -> None:
        client = PollingClient([])
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ) as build_client,
            mock.patch.object(workspace.time, "monotonic", side_effect=[100.0, 101.0]),
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(credential_envelope())
            )

            first = tinyhat_context.inject_tinyhat_context(
                user_message="Connect my Google account",
                is_first_turn=False,
            )
            second = tinyhat_context.inject_tinyhat_context(
                user_message="Check my Google connection",
                is_first_turn=False,
            )
            credentials, verification = workspace._verified_credentials()

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(verification, "match")
        self.assertEqual(credentials["email"], "owner@example.com")
        self.assertEqual(len(client.gets), 2)
        self.assertEqual(
            build_client.call_args_list,
            [
                mock.call(
                    timeout_seconds=workspace.CONTEXT_ASSIGNMENT_CHECK_TIMEOUT_SECONDS
                ),
                mock.call(),
            ],
        )

    def test_context_assignment_cache_expires_after_short_ttl(self) -> None:
        client = PollingClient([])
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                workspace,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ) as build_client,
            mock.patch.object(
                workspace.time,
                "monotonic",
                side_effect=[100.0, 100.5, 131.0],
            ),
        ):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(credential_envelope())
            )

            self.assertEqual(
                workspace.remove_credentials_if_assignment_changed_for_context(),
                "match",
            )
            self.assertEqual(
                workspace.remove_credentials_if_assignment_changed_for_context(),
                "match",
            )
            self.assertEqual(
                workspace.remove_credentials_if_assignment_changed_for_context(),
                "match",
            )

        self.assertEqual(len(client.gets), 2)
        self.assertEqual(build_client.call_count, 2)
        for call in build_client.call_args_list:
            self.assertEqual(
                call,
                mock.call(
                    timeout_seconds=workspace.CONTEXT_ASSIGNMENT_CHECK_TIMEOUT_SECONDS
                ),
            )

    def test_context_assignment_check_does_not_cache_replaced_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(credential_envelope())
            )
            replacement = credential_envelope()
            replacement["tinyhat_assignment_binding"] = "replacement-binding-456"

            def replace_during_check(**_kwargs):
                workspace._atomic_save_credentials(
                    workspace._normalize_credentials(replacement)
                )
                return "match"

            with mock.patch.object(
                workspace,
                "remove_credentials_if_assignment_changed",
                side_effect=replace_during_check,
            ):
                result = workspace.remove_credentials_if_assignment_changed_for_context()

            self.assertEqual(result, "retry")
            self.assertEqual(workspace._context_assignment_check_cache, {})

    def test_connect_google_workspace_phrase_injects_connection_route(self) -> None:
        with mock.patch.object(
            tinyhat_context,
            "remove_credentials_if_assignment_changed_for_context",
            return_value="not_present",
        ):
            result = tinyhat_context.inject_tinyhat_context(
                user_message="Connect my Google Workspace",
                is_first_turn=False,
            )

        self.assertIn("tinyhat_google_workspace with action=connect", result["context"])
        self.assertIn("Never substitute action=status", result["context"])
        self.assertIn("never claim an earlier button is still usable", result["context"])
        self.assertIn("native Connect Google Telegram button", result["context"])
        self.assertIn(
            "Never paste, repeat, or return a plain authorization link", result["context"]
        )

    def test_revoke_google_phrase_injects_button_owned_disconnect_route(self) -> None:
        with mock.patch.object(
            tinyhat_context,
            "remove_credentials_if_assignment_changed_for_context",
            return_value="match",
        ):
            result = tinyhat_context.inject_tinyhat_context(
                user_message="Revoke my Google Workspace connection",
                is_first_turn=False,
            )

        self.assertIn("action=disconnect", result["context"])
        self.assertIn("never pass confirmed=true", result["context"])
        self.assertIn("exactly one Revoke this Computer's access", result["context"])
        self.assertIn("final Confirm revoke and Cancel", result["context"])
        self.assertIn("send a duplicate reply", result["context"])

    def test_credential_symlink_is_never_followed_or_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            workspace.STATE_DIR.mkdir(parents=True)
            target = Path(tmp) / "outside.json"
            target.write_text("outside", encoding="utf-8")
            workspace.CREDENTIALS_PATH.symlink_to(target)

            with self.assertRaises(workspace.GoogleWorkspaceError):
                workspace._atomic_save_credentials(
                    workspace._normalize_credentials(credential_envelope())
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "outside")

    def test_disconnect_starts_button_ceremony_without_trusting_confirmed(self) -> None:
        expected = {
            "status": "waiting_for_user",
            "button_sent": True,
            "connected": True,
        }
        with mock.patch.object(
            workspace,
            "_start_disconnect_intent",
            return_value=expected,
        ) as start:
            without_boolean = json.loads(tools.google_workspace({"action": "disconnect"}))
            with_model_boolean = json.loads(
                tools.google_workspace({"action": "disconnect", "confirmed": True})
            )

        self.assertEqual(without_boolean, expected)
        self.assertEqual(with_model_boolean, expected)
        self.assertEqual(start.call_count, 2)

    def test_disconnect_requires_positive_trusted_telegram_user_id(self) -> None:
        for chat_id in ("", "not-a-user", "0", "-100123"):
            with (
                self.subTest(chat_id=chat_id),
                mock.patch.object(
                    tools,
                    "_telegram_credentials",
                    return_value=("telegram-bot-secret", chat_id),
                ),
                self.assertRaises(workspace.GoogleWorkspaceError),
            ):
                workspace._trusted_telegram_user_id()

    def test_disconnect_creates_worker_before_activate_and_returns_no_intent_secret(
        self,
    ) -> None:
        client = DisconnectClient()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            workspace._atomic_save_credentials(
                workspace._normalize_credentials(credential_envelope())
            )
            events = client.events

            def start_worker(**_kwargs) -> None:
                events.append("worker")

            with (
                mock.patch.object(
                    workspace,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    tools,
                    "_telegram_credentials",
                    return_value=("telegram-bot-secret", "424242"),
                ),
                mock.patch.object(
                    workspace,
                    "_start_disconnect_worker_process",
                    side_effect=start_worker,
                ),
            ):
                result = workspace._start_disconnect_intent()

            self.assertEqual(result["status"], "waiting_for_user")
            self.assertTrue(result["button_sent"])
            self.assertEqual(events[:4], ["binding", "create", "binding", "worker"])
            self.assertEqual(events[4], "activate")
            create_payloads = [
                payload for path, payload in client.posts if path.endswith("/disconnect-intents")
            ]
            self.assertEqual(create_payloads, [{"telegram_user_id": 424242}])
            self.assertNotIn("telegram-bot-secret", json.dumps(client.posts))
            serialized = json.dumps(result, sort_keys=True)
            self.assertNotIn("gwd_test123", serialized)
            self.assertNotIn("disconnect-owner-token", serialized)
            self.assertNotIn("http", serialized.lower())
            self.assertNotIn("url", serialized.lower())
            self.assertEqual(
                stat.S_IMODE(workspace.ACTIVE_DISCONNECT_PATH.stat().st_mode),
                0o600,
            )
            state_path = workspace.DISCONNECTS_DIR / "gwd_test123" / "intent.json"
            self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
            marker_text = workspace.ACTIVE_DISCONNECT_PATH.read_text(encoding="utf-8")
            self.assertNotIn("disconnect-owner-token", marker_text)

    def test_disconnect_activation_failure_preserves_existing_credential(self) -> None:
        client = DisconnectClient(button_sent=False)
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            before = workspace.CREDENTIALS_PATH.read_bytes()
            with (
                mock.patch.object(
                    workspace,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    tools,
                    "_telegram_credentials",
                    return_value=("telegram-bot-secret", "424242"),
                ),
                mock.patch.object(workspace, "_start_disconnect_worker_process"),
            ):
                result = json.loads(tools.google_workspace({"action": "disconnect"}))

            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["button_sent"])
            self.assertEqual(workspace.CREDENTIALS_PATH.read_bytes(), before)
            self.assertFalse(workspace.ACTIVE_DISCONNECT_PATH.exists())
            complete_payloads = [
                payload for path, payload in client.posts if path.endswith("/complete")
            ]
            self.assertEqual(complete_payloads[-1]["outcome"], "failed")
            self.assertEqual(
                complete_payloads[-1]["error_code"],
                "activation_failed",
            )

    def test_disconnect_does_not_activate_before_worker_is_ready(self) -> None:
        client = DisconnectClient()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            before = workspace.CREDENTIALS_PATH.read_bytes()
            with (
                mock.patch.object(
                    workspace,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    tools,
                    "_telegram_credentials",
                    return_value=("telegram-bot-secret", "424242"),
                ),
                mock.patch.object(
                    workspace,
                    "_start_disconnect_worker_process",
                    side_effect=workspace.GoogleWorkspaceError("worker not ready"),
                ),
            ):
                result = json.loads(tools.google_workspace({"action": "disconnect"}))

            self.assertEqual(result["status"], "failed")
            self.assertNotIn("activate", client.events)
            self.assertEqual(workspace.CREDENTIALS_PATH.read_bytes(), before)
            complete_payloads = [
                payload for path, payload in client.posts if path.endswith("/complete")
            ]
            self.assertEqual(complete_payloads[-1]["outcome"], "failed")
            self.assertEqual(complete_payloads[-1]["error_code"], "worker_start_failed")

    def test_cancelled_disconnect_preserves_credential_byte_for_byte(self) -> None:
        client = DisconnectClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "cancelled",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            before = workspace.CREDENTIALS_PATH.read_bytes()
            intent = self._disconnect_intent(client=client, credentials=saved)
            self._activate_disconnect_intent(intent)

            outcome = workspace._poll_disconnect_intent(intent)

            self.assertEqual(outcome, "cancelled")
            self.assertEqual(workspace.CREDENTIALS_PATH.read_bytes(), before)
            self.assertFalse(workspace.ACTIVE_DISCONNECT_PATH.exists())
            self.assertFalse(any(path.endswith("/complete") for path, _ in client.posts))

    def test_confirmed_disconnect_deletes_matching_generation_then_completes(
        self,
    ) -> None:
        client = DisconnectClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "confirmed",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            intent = self._disconnect_intent(client=client, credentials=saved)
            old_handoff_client = PollingClient([])
            old_handoff = self._worker_handoff(client=old_handoff_client)
            self._activate_handoff()
            self._activate_disconnect_intent(intent)

            with self._captured_notices() as notices:
                outcome = workspace._poll_disconnect_intent(intent)
                workspace._poll_and_install(old_handoff)

            self.assertEqual(outcome, "disconnected")
            self.assertFalse(workspace.CREDENTIALS_PATH.exists())
            self.assertFalse(workspace.ACTIVE_DISCONNECT_PATH.exists())
            self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())
            self.assertEqual(old_handoff_client.posts[-1][1]["installed"], False)
            self.assertEqual(notices, ["superseded"])
            complete_payloads = [
                payload for path, payload in client.posts if path.endswith("/complete")
            ]
            self.assertEqual(
                complete_payloads,
                [{"owner_token": intent.owner_token, "outcome": "disconnected"}],
            )
            self.assertLess(client.events.index("binding"), client.events.index("complete"))

    def test_deletion_claim_is_durable_and_precedes_delete_and_complete(self) -> None:
        receipt_seen_at_claim: list[bool] = []

        class ClaimInspectingClient(DisconnectClient):
            def post_json(self, path, payload):
                if path.endswith("/claim"):
                    receipt_seen_at_claim.append(receipt_path.exists())
                return super().post_json(path, payload)

        client = ClaimInspectingClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "confirmed",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            intent = self._disconnect_intent(client=client, credentials=saved)
            state_path = workspace._write_disconnect_worker_state(
                intent=intent,
                credential_generation=intent.credential_generation,
            )
            receipt_path = state_path.parent / "completion-receipt.json"
            self._activate_disconnect_intent(intent)
            real_delete = workspace._delete_credentials_locked

            def delete_once() -> None:
                client.events.append("delete")
                real_delete()

            with (
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    workspace,
                    "_delete_credentials_locked",
                    side_effect=delete_once,
                ) as delete,
            ):
                google_workspace_disconnect_worker.run_worker(
                    intent_id=intent.intent_id,
                    state_path=state_path,
                )

            delete.assert_called_once_with()
            self.assertEqual(receipt_seen_at_claim, [True])
            claim_payloads = [payload for path, payload in client.posts if path.endswith("/claim")]
            self.assertEqual(claim_payloads, [{"owner_token": intent.owner_token}])
            self.assertLess(client.events.index("claim"), client.events.index("delete"))
            self.assertLess(client.events.index("delete"), client.events.index("complete"))
            self.assertFalse(workspace.CREDENTIALS_PATH.exists())
            self.assertFalse(state_path.parent.exists())

    def test_reconnect_superseding_before_claim_preserves_credential(self) -> None:
        client = DisconnectClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "confirmed",
                }
            ],
            claim_status="superseded",
            deletion_claimed=False,
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            before = workspace.CREDENTIALS_PATH.read_bytes()
            intent = self._disconnect_intent(client=client, credentials=saved)
            self._activate_disconnect_intent(intent)

            with mock.patch.object(
                workspace,
                "_delete_credentials_locked",
                side_effect=AssertionError("superseded claim must not delete"),
            ) as delete:
                outcome = workspace._poll_disconnect_intent(intent)

            self.assertEqual(outcome, "superseded")
            delete.assert_not_called()
            self.assertEqual(workspace.CREDENTIALS_PATH.read_bytes(), before)
            self.assertIn("claim", client.events)
            self.assertFalse(workspace.ACTIVE_DISCONNECT_PATH.exists())

    def test_marker_cleanup_failure_after_unlink_stays_completion_pending(self) -> None:
        client = DisconnectClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "confirmed",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            intent = self._disconnect_intent(client=client, credentials=saved)
            state_path = workspace._write_disconnect_worker_state(
                intent=intent,
                credential_generation=intent.credential_generation,
            )
            self._activate_disconnect_intent(intent)

            with (
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    workspace,
                    "_remove_active_disconnect_marker_if_matches",
                    side_effect=OSError("marker cleanup failed"),
                ),
                mock.patch.object(
                    workspace,
                    "_complete_disconnect_intent",
                    side_effect=RuntimeError("platform outage"),
                ) as complete,
                mock.patch.object(
                    workspace.time,
                    "monotonic",
                    side_effect=[0, 1, 3602],
                ),
                mock.patch.object(workspace.time, "sleep"),
            ):
                google_workspace_disconnect_worker.run_worker(
                    intent_id=intent.intent_id,
                    state_path=state_path,
                )

            self.assertFalse(workspace.CREDENTIALS_PATH.exists())
            complete.assert_called_once_with(
                intent=mock.ANY,
                outcome="disconnected",
                error_code=None,
            )
            receipt = json.loads(
                (state_path.parent / "completion-receipt.json").read_text(encoding="utf-8")
            )
            self.assertEqual(receipt["phase"], "completion_pending")
            self.assertTrue(state_path.exists())

    def test_unclaimed_absent_credential_never_reports_failed_completion(self) -> None:
        client = DisconnectClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "confirmed",
                }
            ],
            claim_status="confirmed",
            deletion_claimed=False,
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            intent = self._disconnect_intent(client=client, credentials=saved)
            self._activate_disconnect_intent(intent)
            workspace.CREDENTIALS_PATH.unlink()

            with mock.patch.object(
                workspace,
                "_delete_credentials_locked",
                side_effect=AssertionError("missing credentials must not be deleted"),
            ) as delete:
                outcome = workspace._poll_disconnect_intent(intent)

            self.assertEqual(outcome, "deletion_claim_pending")
            delete.assert_not_called()
            self.assertFalse(any(path.endswith("/complete") for path, _ in client.posts))

    def test_absent_credential_claim_ambiguity_retains_and_replays(self) -> None:
        client = DisconnectClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "confirmed",
                }
            ],
            claim_status="confirmed",
            deletion_claimed=False,
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            intent = self._disconnect_intent(client=client, credentials=saved)
            state_path = workspace._write_disconnect_worker_state(
                intent=intent,
                credential_generation=intent.credential_generation,
            )
            self._activate_disconnect_intent(intent)
            workspace.CREDENTIALS_PATH.unlink()

            with (
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    workspace,
                    "_delete_credentials_locked",
                    side_effect=AssertionError("absent credentials must not be deleted"),
                ) as first_delete,
            ):
                google_workspace_disconnect_worker.run_worker(
                    intent_id=intent.intent_id,
                    state_path=state_path,
                )

            first_delete.assert_not_called()
            self.assertTrue(state_path.exists())
            receipt_path = state_path.parent / "completion-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["phase"], "delete_pending")
            self.assertFalse(any(path.endswith("/complete") for path, _ in client.posts))

            client.deletion_claimed = True
            with (
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    workspace,
                    "_delete_credentials_locked",
                    side_effect=AssertionError("claim replay must not re-delete"),
                ) as replay_delete,
            ):
                google_workspace_disconnect_worker.run_worker(
                    intent_id=intent.intent_id,
                    state_path=state_path,
                )

            replay_delete.assert_not_called()
            self.assertEqual(client.events.count("claim"), 2)
            complete_payloads = [
                payload for path, payload in client.posts if path.endswith("/complete")
            ]
            self.assertEqual(
                complete_payloads,
                [{"owner_token": intent.owner_token, "outcome": "disconnected"}],
            )
            self.assertFalse(state_path.parent.exists())

    def test_confirmed_disconnect_retries_past_one_minute_without_redeleting(self) -> None:
        client = DisconnectClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "confirmed",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            intent = self._disconnect_intent(client=client, credentials=saved)
            self._activate_disconnect_intent(intent)
            real_delete = workspace._delete_credentials_locked

            with (
                mock.patch.object(
                    workspace,
                    "_complete_disconnect_intent",
                    side_effect=[RuntimeError("platform outage"), {"status": "disconnected"}],
                ) as complete,
                mock.patch.object(
                    workspace,
                    "_delete_credentials_locked",
                    wraps=real_delete,
                ) as delete,
                mock.patch.object(
                    workspace.time,
                    "monotonic",
                    side_effect=[0, 61],
                ),
                mock.patch.object(workspace.time, "sleep"),
            ):
                outcome = workspace._poll_disconnect_intent(intent)

            self.assertEqual(outcome, "disconnected")
            self.assertEqual(complete.call_count, 2)
            delete.assert_called_once_with()
            self.assertFalse(workspace.CREDENTIALS_PATH.exists())
            self.assertFalse(workspace.ACTIVE_DISCONNECT_PATH.exists())

    def test_confirmed_disconnect_ignores_stale_handoff_scratch_garbage(self) -> None:
        client = DisconnectClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "confirmed",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            intent = self._disconnect_intent(client=client, credentials=saved)
            self._activate_disconnect_intent(intent)
            workspace.HANDOFFS_DIR.mkdir(mode=0o700)
            stale_entry = workspace.HANDOFFS_DIR / "unexpected-owner-file"
            stale_entry.write_text("stale", encoding="utf-8")
            stale_entry.chmod(0o600)
            workspace._write_active_handoff_marker(
                handoff_id="gwo_stale123",
                owner_token="stale-owner-token",
            )

            outcome = workspace._poll_disconnect_intent(intent)

            self.assertEqual(outcome, "disconnected")
            self.assertFalse(workspace.CREDENTIALS_PATH.exists())
            self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())
            self.assertTrue(stale_entry.exists())
            completed = [payload for path, payload in client.posts if path.endswith("/complete")]
            self.assertEqual(completed[-1]["outcome"], "disconnected")

    def test_confirmed_stale_intent_cannot_delete_replacement_credential(self) -> None:
        client = DisconnectClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "confirmed",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            original = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(original)
            intent = self._disconnect_intent(client=client, credentials=original)
            self._activate_disconnect_intent(intent)
            replacement = dict(original)
            replacement["refresh_token"] = "replacement-refresh-value"
            replacement["connected_at"] = "2030-01-02T00:00:00+00:00"
            workspace._atomic_save_credentials(replacement)
            before = workspace.CREDENTIALS_PATH.read_bytes()

            outcome = workspace._poll_disconnect_intent(intent)

            self.assertEqual(outcome, "credential_changed")
            self.assertEqual(workspace.CREDENTIALS_PATH.read_bytes(), before)
            failed = [payload for path, payload in client.posts if path.endswith("/complete")][-1]
            self.assertEqual(failed["outcome"], "failed")
            self.assertEqual(failed["error_code"], "credential_changed")

    def test_confirmed_disconnect_assignment_change_preserves_credential(self) -> None:
        client = DisconnectClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "confirmed",
                }
            ],
            binding="new-assignment-binding",
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            before = workspace.CREDENTIALS_PATH.read_bytes()
            intent = self._disconnect_intent(client=client, credentials=saved)
            self._activate_disconnect_intent(intent)

            outcome = workspace._poll_disconnect_intent(intent)

            self.assertEqual(outcome, "assignment_changed")
            self.assertEqual(workspace.CREDENTIALS_PATH.read_bytes(), before)

    def test_superseded_disconnect_preserves_credential(self) -> None:
        client = DisconnectClient()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            before = workspace.CREDENTIALS_PATH.read_bytes()
            intent = self._disconnect_intent(client=client, credentials=saved)

            outcome = workspace._poll_disconnect_intent(intent)

            self.assertEqual(outcome, "superseded")
            self.assertEqual(workspace.CREDENTIALS_PATH.read_bytes(), before)
            complete = [payload for path, payload in client.posts if path.endswith("/complete")][-1]
            self.assertEqual(complete["error_code"], "superseded")

    def test_failed_and_expired_disconnect_states_preserve_credential(self) -> None:
        for terminal_status in ("failed", "expired"):
            with self.subTest(terminal_status=terminal_status):
                client = DisconnectClient(
                    [
                        {
                            "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                            "intent_id": "gwd_test123",
                            "status": terminal_status,
                        }
                    ]
                )
                with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
                    saved = workspace._normalize_credentials(credential_envelope())
                    workspace._atomic_save_credentials(saved)
                    before = workspace.CREDENTIALS_PATH.read_bytes()
                    intent = self._disconnect_intent(
                        client=client,
                        credentials=saved,
                    )
                    self._activate_disconnect_intent(intent)

                    outcome = workspace._poll_disconnect_intent(intent)

                    self.assertEqual(outcome, terminal_status)
                    self.assertEqual(workspace.CREDENTIALS_PATH.read_bytes(), before)
                    self.assertFalse(workspace.ACTIVE_DISCONNECT_PATH.exists())

    def test_poll_response_cannot_extend_disconnect_deadline(self) -> None:
        now = datetime.now(timezone.utc)
        client = DisconnectClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "awaiting_confirmation",
                    "expires_at": (now + timedelta(minutes=5)).isoformat(),
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            current = self._disconnect_intent(client=client, credentials=saved)
            intent = workspace.GoogleWorkspaceDisconnectIntent(
                client=current.client,
                platform_auth=current.platform_auth,
                intent_id=current.intent_id,
                owner_token=current.owner_token,
                credential_generation=current.credential_generation,
                expires_at=(now + timedelta(seconds=1)).isoformat(),
                poll_after_ms=current.poll_after_ms,
            )
            self._activate_disconnect_intent(intent)
            before = workspace.CREDENTIALS_PATH.read_bytes()

            with (
                mock.patch.object(
                    workspace.time,
                    "time",
                    side_effect=[now.timestamp(), now.timestamp() + 2],
                ),
                mock.patch.object(workspace.time, "sleep"),
            ):
                outcome = workspace._poll_disconnect_intent(intent)

            self.assertEqual(outcome, "expired")
            self.assertEqual(client.events.count("poll"), 1)
            self.assertEqual(workspace.CREDENTIALS_PATH.read_bytes(), before)
            self.assertFalse(workspace.ACTIVE_DISCONNECT_PATH.exists())

    def test_local_disconnect_deadline_expires_platform_without_deleting(self) -> None:
        now = datetime.now(timezone.utc)
        client = DisconnectClient()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            before = workspace.CREDENTIALS_PATH.read_bytes()
            current = self._disconnect_intent(client=client, credentials=saved)
            expired = workspace.GoogleWorkspaceDisconnectIntent(
                client=current.client,
                platform_auth=current.platform_auth,
                intent_id=current.intent_id,
                owner_token=current.owner_token,
                credential_generation=current.credential_generation,
                expires_at=(now - timedelta(seconds=1)).isoformat(),
                poll_after_ms=current.poll_after_ms,
            )
            self._activate_disconnect_intent(expired)

            with (
                mock.patch.object(workspace.time, "time", return_value=now.timestamp()),
                mock.patch.object(
                    workspace.time,
                    "monotonic",
                    side_effect=[0, 61],
                ),
                mock.patch.object(workspace.time, "sleep"),
                mock.patch.object(
                    workspace,
                    "_complete_disconnect_intent",
                    side_effect=[RuntimeError("platform outage"), {"status": "expired"}],
                ) as complete,
            ):
                outcome = workspace._poll_disconnect_intent(expired)

            self.assertEqual(outcome, "expired")
            self.assertEqual(workspace.CREDENTIALS_PATH.read_bytes(), before)
            self.assertFalse(workspace.ACTIVE_DISCONNECT_PATH.exists())
            self.assertEqual(complete.call_count, 2)
            for call in complete.call_args_list:
                self.assertEqual(call.kwargs["intent"], expired)
                self.assertEqual(call.kwargs["outcome"], "failed")
                self.assertEqual(call.kwargs["error_code"], "expired")

    def test_disconnect_worker_state_is_owner_only_and_owner_token_stays_off_argv(
        self,
    ) -> None:
        client = DisconnectClient()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            intent = self._disconnect_intent(client=client, credentials=saved)
            state_path = workspace._write_disconnect_worker_state(
                intent=intent,
                credential_generation=intent.credential_generation,
            )
            command = workspace._disconnect_worker_command(
                intent_id=intent.intent_id,
                state_path=state_path,
                package_dir=Path(workspace.__file__).resolve().parent,
            )

            self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
            self.assertIn(intent.owner_token, state_path.read_text(encoding="utf-8"))
            self.assertNotIn(intent.owner_token, " ".join(command))
            self.assertIn("google_workspace_disconnect_worker.py", command[1])

    def test_disconnect_process_start_waits_for_worker_readiness(self) -> None:
        client = DisconnectClient()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            intent = self._disconnect_intent(client=client, credentials=saved)
            state_path = workspace._write_disconnect_worker_state(
                intent=intent,
                credential_generation=intent.credential_generation,
            )

            def start_process(*_args, **_kwargs):
                workspace._write_disconnect_worker_ready(
                    intent_id=intent.intent_id,
                    state_path=state_path,
                )
                return mock.Mock()

            with (
                mock.patch.object(
                    workspace,
                    "_start_disconnect_worker_with_systemd",
                    return_value=False,
                ),
                mock.patch.object(
                    workspace.subprocess,
                    "Popen",
                    side_effect=start_process,
                ) as popen,
            ):
                workspace._start_disconnect_worker_process(
                    intent_id=intent.intent_id,
                    state_path=state_path,
                )

            popen.assert_called_once()
            self.assertTrue((state_path.parent / "ready.json").exists())

    def test_later_plugin_use_auto_starts_retained_completion_receipt(self) -> None:
        client = DisconnectClient()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            intent = self._disconnect_intent(client=client, credentials=saved)
            state_path = workspace._write_disconnect_worker_state(
                intent=intent,
                credential_generation=intent.credential_generation,
            )
            workspace._write_disconnect_completion_receipt(
                intent=intent,
                state_path=state_path,
                phase="completion_pending",
                outcome="disconnected",
                error_code=None,
            )

            with mock.patch.object(
                workspace,
                "_start_disconnect_worker_process",
            ) as start_worker:
                started = workspace._resume_retained_disconnect_workers()

            self.assertEqual(started, 1)
            start_worker.assert_called_once_with(
                intent_id=intent.intent_id,
                state_path=state_path,
            )

            with (
                mock.patch.object(
                    workspace,
                    "_resume_retained_disconnect_workers",
                    return_value=1,
                ) as auto_resume,
                mock.patch.object(
                    workspace,
                    "_status_payload",
                    return_value={"status": "not_connected", "connected": False},
                ),
            ):
                result = json.loads(workspace.google_workspace({"action": "status"}))

            self.assertFalse(result["connected"])
            auto_resume.assert_called_once_with()

    def test_later_plugin_use_sweeps_expired_receiptless_disconnect_state(self) -> None:
        client = DisconnectClient()
        expired_at = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            intent = self._disconnect_intent(
                client=client,
                credentials=saved,
                expires_at=expired_at,
            )
            state_path = workspace._write_disconnect_worker_state(
                intent=intent,
                credential_generation=intent.credential_generation,
            )
            self._activate_disconnect_intent(intent)

            with mock.patch.object(
                workspace,
                "_start_disconnect_worker_process",
            ) as start_worker:
                started = workspace._resume_retained_disconnect_workers()

            self.assertEqual(started, 0)
            start_worker.assert_not_called()
            self.assertFalse(state_path.parent.exists())
            self.assertFalse(workspace.ACTIVE_DISCONNECT_PATH.exists())

    def test_orphan_sweep_preserves_unexpired_or_receipted_disconnect_state(self) -> None:
        client = DisconnectClient()
        expired_at = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            unexpired = self._disconnect_intent(
                client=client,
                credentials=saved,
                intent_id="gwd_unexpired123",
            )
            unexpired_path = workspace._write_disconnect_worker_state(
                intent=unexpired,
                credential_generation=unexpired.credential_generation,
            )
            receipted = self._disconnect_intent(
                client=client,
                credentials=saved,
                intent_id="gwd_receipted123",
                expires_at=expired_at,
            )
            receipted_path = workspace._write_disconnect_worker_state(
                intent=receipted,
                credential_generation=receipted.credential_generation,
            )
            workspace._write_disconnect_completion_receipt(
                intent=receipted,
                state_path=receipted_path,
                phase="completion_pending",
                outcome="disconnected",
                error_code=None,
            )

            with mock.patch.object(
                workspace,
                "_start_disconnect_worker_process",
            ) as start_worker:
                started = workspace._resume_retained_disconnect_workers()

            self.assertEqual(started, 1)
            self.assertTrue(unexpired_path.parent.exists())
            self.assertTrue(receipted_path.parent.exists())
            start_worker.assert_called_once_with(
                intent_id=receipted.intent_id,
                state_path=receipted_path,
            )

    def test_orphan_sweep_is_bounded_and_skips_unsafe_state(self) -> None:
        client = DisconnectClient()
        expired_at = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            paths: list[Path] = []
            for index in range(workspace.DISCONNECT_ORPHAN_SWEEP_DELETE_LIMIT + 2):
                intent = self._disconnect_intent(
                    client=client,
                    credentials=saved,
                    intent_id=f"gwd_sweep{index:03d}",
                    expires_at=expired_at,
                )
                paths.append(
                    workspace._write_disconnect_worker_state(
                        intent=intent,
                        credential_generation=intent.credential_generation,
                    )
                )

            unsafe = self._disconnect_intent(
                client=client,
                credentials=saved,
                intent_id="gwd_unsafe123",
                expires_at=expired_at,
            )
            unsafe_path = workspace._write_disconnect_worker_state(
                intent=unsafe,
                credential_generation=unsafe.credential_generation,
            )
            unsafe_path.parent.chmod(0o755)
            malformed = self._disconnect_intent(
                client=client,
                credentials=saved,
                intent_id="gwd_malformed123",
                expires_at=expired_at,
            )
            malformed_path = workspace._write_disconnect_worker_state(
                intent=malformed,
                credential_generation=malformed.credential_generation,
            )
            malformed_path.write_text("{}", encoding="utf-8")
            malformed_path.chmod(0o600)

            started = workspace._resume_retained_disconnect_workers()

            self.assertEqual(started, 0)
            self.assertEqual(
                sum(path.parent.exists() for path in paths),
                2,
            )
            self.assertTrue(unsafe_path.parent.exists())
            self.assertTrue(malformed_path.parent.exists())

    def test_disconnect_worker_cleans_state_when_platform_setup_fails(self) -> None:
        client = DisconnectClient()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            intent = self._disconnect_intent(client=client, credentials=saved)
            state_path = workspace._write_disconnect_worker_state(
                intent=intent,
                credential_generation=intent.credential_generation,
            )
            with (
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "build_platform_client",
                    side_effect=RuntimeError("platform unavailable"),
                ),
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "DISCONNECT_WORKER_READY_TIMEOUT_SECONDS",
                    0,
                ),
                self.assertRaises(RuntimeError),
            ):
                google_workspace_disconnect_worker.run_worker(
                    intent_id=intent.intent_id,
                    state_path=state_path,
                )

            self.assertFalse(state_path.parent.exists())

    def test_disconnect_worker_retries_startup_and_signals_readiness(self) -> None:
        client = DisconnectClient()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            intent = self._disconnect_intent(client=client, credentials=saved)
            state_path = workspace._write_disconnect_worker_state(
                intent=intent,
                credential_generation=intent.credential_generation,
            )
            ready_seen: list[bool] = []

            def inspect_ready(_intent, **_kwargs) -> str:
                ready_path = state_path.parent / "ready.json"
                ready_seen.append(ready_path.exists())
                self.assertEqual(stat.S_IMODE(ready_path.stat().st_mode), 0o600)
                return "cancelled"

            with (
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "build_platform_client",
                    side_effect=[RuntimeError("transient"), (client, "local_dev")],
                ) as build_client,
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "_poll_disconnect_intent",
                    side_effect=inspect_ready,
                ),
                mock.patch.object(google_workspace_disconnect_worker.time, "sleep"),
            ):
                google_workspace_disconnect_worker.run_worker(
                    intent_id=intent.intent_id,
                    state_path=state_path,
                )

            self.assertEqual(build_client.call_count, 2)
            self.assertEqual(ready_seen, [True])
            self.assertFalse(state_path.parent.exists())

    def test_unacknowledged_disconnect_completion_retains_owner_state(self) -> None:
        client = DisconnectClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "confirmed",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            intent = self._disconnect_intent(client=client, credentials=saved)
            state_path = workspace._write_disconnect_worker_state(
                intent=intent,
                credential_generation=intent.credential_generation,
            )
            self._activate_disconnect_intent(intent)
            real_delete = workspace._delete_credentials_locked

            with (
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    workspace,
                    "_complete_disconnect_intent",
                    side_effect=RuntimeError("platform outage"),
                ) as complete,
                mock.patch.object(
                    workspace,
                    "_delete_credentials_locked",
                    wraps=real_delete,
                ) as delete,
                mock.patch.object(
                    workspace.time,
                    "monotonic",
                    side_effect=[0, 1, 3602],
                ),
                mock.patch.object(workspace.time, "sleep"),
            ):
                google_workspace_disconnect_worker.run_worker(
                    intent_id=intent.intent_id,
                    state_path=state_path,
                )

            delete.assert_called_once_with()
            complete.assert_called_once_with(
                intent=mock.ANY,
                outcome="disconnected",
                error_code=None,
            )
            self.assertFalse(workspace.CREDENTIALS_PATH.exists())
            self.assertFalse(workspace.ACTIVE_DISCONNECT_PATH.exists())
            self.assertTrue(state_path.exists())
            self.assertTrue((state_path.parent / "ready.json").exists())
            receipt_path = state_path.parent / "completion-receipt.json"
            self.assertTrue(receipt_path.exists())
            self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)
            self.assertEqual(
                json.loads(receipt_path.read_text(encoding="utf-8"))["phase"],
                "completion_pending",
            )

            with (
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    workspace,
                    "_complete_disconnect_intent",
                    return_value={"status": "disconnected"},
                ) as resumed_complete,
                mock.patch.object(
                    workspace,
                    "_delete_credentials_locked",
                    side_effect=AssertionError("completion replay must not delete again"),
                ) as replay_delete,
            ):
                google_workspace_disconnect_worker.run_worker(
                    intent_id=intent.intent_id,
                    state_path=state_path,
                )

            replay_delete.assert_not_called()
            resumed_complete.assert_called_once_with(
                intent=mock.ANY,
                outcome="disconnected",
                error_code=None,
            )
            self.assertFalse(state_path.parent.exists())

    def test_receipt_promotion_failure_after_delete_replays_as_disconnected(self) -> None:
        client = DisconnectClient(
            [
                {
                    "schema": "tinyhat_google_workspace_disconnect_intent_v1",
                    "intent_id": "gwd_test123",
                    "status": "confirmed",
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            intent = self._disconnect_intent(client=client, credentials=saved)
            state_path = workspace._write_disconnect_worker_state(
                intent=intent,
                credential_generation=intent.credential_generation,
            )
            self._activate_disconnect_intent(intent)
            real_write_receipt = (
                google_workspace_disconnect_worker._write_disconnect_completion_receipt
            )

            def fail_only_post_delete_promotion(**kwargs) -> None:
                if kwargs["phase"] == "completion_pending":
                    raise OSError("receipt promotion failed")
                real_write_receipt(**kwargs)

            with (
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "_write_disconnect_completion_receipt",
                    side_effect=fail_only_post_delete_promotion,
                ),
                mock.patch.object(
                    workspace,
                    "_complete_disconnect_intent",
                    side_effect=RuntimeError("platform outage"),
                ) as complete,
                mock.patch.object(
                    workspace.time,
                    "monotonic",
                    side_effect=[0, 1, 3602],
                ),
                mock.patch.object(workspace.time, "sleep"),
            ):
                google_workspace_disconnect_worker.run_worker(
                    intent_id=intent.intent_id,
                    state_path=state_path,
                )

            self.assertFalse(workspace.CREDENTIALS_PATH.exists())
            complete.assert_called_once_with(
                intent=mock.ANY,
                outcome="disconnected",
                error_code=None,
            )
            receipt_path = state_path.parent / "completion-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["phase"], "delete_pending")

            with (
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    workspace,
                    "_complete_disconnect_intent",
                    return_value={"status": "disconnected"},
                ) as resumed_complete,
                mock.patch.object(
                    workspace,
                    "_delete_credentials_locked",
                    side_effect=AssertionError("replay must not delete again"),
                ) as replay_delete,
            ):
                google_workspace_disconnect_worker.run_worker(
                    intent_id=intent.intent_id,
                    state_path=state_path,
                )

            replay_delete.assert_not_called()
            resumed_complete.assert_called_once_with(
                intent=mock.ANY,
                outcome="disconnected",
                error_code=None,
            )
            self.assertEqual(client.events.count("claim"), 2)
            self.assertFalse(state_path.parent.exists())

    def test_late_disconnect_worker_clears_expired_marker_without_deleting(self) -> None:
        client = DisconnectClient()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            before = workspace.CREDENTIALS_PATH.read_bytes()
            current = self._disconnect_intent(client=client, credentials=saved)
            expired = workspace.GoogleWorkspaceDisconnectIntent(
                client=current.client,
                platform_auth=current.platform_auth,
                intent_id=current.intent_id,
                owner_token=current.owner_token,
                credential_generation=current.credential_generation,
                expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                poll_after_ms=current.poll_after_ms,
            )
            state_path = workspace._write_disconnect_worker_state(
                intent=expired,
                credential_generation=expired.credential_generation,
            )
            self._activate_disconnect_intent(expired)

            with mock.patch.object(
                google_workspace_disconnect_worker,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ):
                google_workspace_disconnect_worker.run_worker(
                    intent_id=expired.intent_id,
                    state_path=state_path,
                )

            self.assertEqual(workspace.CREDENTIALS_PATH.read_bytes(), before)
            self.assertFalse(workspace.ACTIVE_DISCONNECT_PATH.exists())
            self.assertFalse(state_path.parent.exists())

    def test_expired_completion_receipt_replays_without_deleting(self) -> None:
        client = DisconnectClient()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            workspace._atomic_save_credentials(saved)
            before = workspace.CREDENTIALS_PATH.read_bytes()
            current = self._disconnect_intent(client=client, credentials=saved)
            expired = workspace.GoogleWorkspaceDisconnectIntent(
                client=current.client,
                platform_auth=current.platform_auth,
                intent_id=current.intent_id,
                owner_token=current.owner_token,
                credential_generation=current.credential_generation,
                expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                poll_after_ms=current.poll_after_ms,
            )
            state_path = workspace._write_disconnect_worker_state(
                intent=expired,
                credential_generation=expired.credential_generation,
            )
            self._activate_disconnect_intent(expired)

            with (
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    workspace,
                    "_complete_disconnect_intent",
                    side_effect=RuntimeError("platform outage"),
                ),
                mock.patch.object(
                    workspace,
                    "_delete_credentials_locked",
                    side_effect=AssertionError("expiry must never delete credentials"),
                ) as delete,
                mock.patch.object(
                    workspace.time,
                    "monotonic",
                    side_effect=[0, 1, 3602],
                ),
                mock.patch.object(workspace.time, "sleep"),
            ):
                google_workspace_disconnect_worker.run_worker(
                    intent_id=expired.intent_id,
                    state_path=state_path,
                )

            delete.assert_not_called()
            self.assertEqual(workspace.CREDENTIALS_PATH.read_bytes(), before)
            self.assertTrue(state_path.exists())
            receipt_path = state_path.parent / "completion-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["phase"], "completion_pending")
            self.assertEqual(receipt["outcome"], "failed")
            self.assertEqual(receipt["error_code"], "expired")

            with (
                mock.patch.object(
                    google_workspace_disconnect_worker,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    workspace,
                    "_complete_disconnect_intent",
                    return_value={"status": "expired"},
                ) as resumed_complete,
                mock.patch.object(
                    workspace,
                    "_delete_credentials_locked",
                    side_effect=AssertionError("expiry replay must never delete"),
                ) as replay_delete,
            ):
                google_workspace_disconnect_worker.run_worker(
                    intent_id=expired.intent_id,
                    state_path=state_path,
                )

            replay_delete.assert_not_called()
            resumed_complete.assert_called_once_with(
                intent=mock.ANY,
                outcome="failed",
                error_code="expired",
            )
            self.assertEqual(workspace.CREDENTIALS_PATH.read_bytes(), before)
            self.assertFalse(state_path.parent.exists())

    def test_connect_supersedes_active_disconnect_before_starting_handoff(self) -> None:
        client = DisconnectClient()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved = workspace._normalize_credentials(credential_envelope())
            intent = self._disconnect_intent(client=client, credentials=saved)
            self._activate_disconnect_intent(intent)
            oauth_client = PollingClient([])
            oauth_client.post_json = mock.Mock(return_value=start_response())

            with (
                mock.patch.object(
                    workspace,
                    "build_platform_client",
                    return_value=(oauth_client, "local_dev"),
                ),
                mock.patch.object(
                    workspace,
                    "_generate_key_pair",
                    return_value=("private", "public"),
                ),
                mock.patch.object(workspace, "_start_worker_process"),
                mock.patch.object(
                    workspace,
                    "_send_google_connect_button",
                    return_value={"sent": True, "ok": True},
                ),
            ):
                result = workspace._start_connection()

            self.assertEqual(result["status"], "waiting_for_user")
            self.assertFalse(workspace.ACTIVE_DISCONNECT_PATH.exists())

    def test_detached_worker_cleans_one_time_state(self) -> None:
        client = PollingClient([{"terminal_state": "cancelled"}])
        generation = "generation-value-that-is-long-enough-123"
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                google_workspace_worker,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            self._captured_notices() as notices,
        ):
            key_path = workspace._write_worker_state(
                handoff_id="gwo_worker123",
                private_key_pem="private-key",
                generation=generation,
                handoff_metadata={
                    "capability_bundle": READONLY_BUNDLE,
                    "services": READONLY_SERVICES,
                    "scopes": READONLY_SCOPES,
                },
            )
            workspace._write_active_handoff_marker(
                handoff_id="gwo_worker123",
                owner_token=workspace._handoff_owner_token(generation),
            )
            google_workspace_worker.run_worker(
                handoff_id="gwo_worker123",
                key_path=key_path,
            )

            self.assertFalse(key_path.parent.exists())
            self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())
            self.assertEqual(notices, ["cancelled"])

    def test_worker_cleans_scratch_when_platform_client_setup_fails(self) -> None:
        generation = "generation-value-that-is-long-enough-123"
        with (
            tempfile.TemporaryDirectory() as tmp,
            self._patched_state(Path(tmp)),
            mock.patch.object(
                google_workspace_worker,
                "build_platform_client",
                side_effect=RuntimeError("offline"),
            ),
        ):
            key_path = workspace._write_worker_state(
                handoff_id="gwo_workerfail123",
                private_key_pem="private-key",
                generation=generation,
                handoff_metadata={
                    "capability_bundle": READONLY_BUNDLE,
                    "services": READONLY_SERVICES,
                    "scopes": READONLY_SCOPES,
                },
            )
            workspace._write_active_handoff_marker(
                handoff_id="gwo_workerfail123",
                owner_token=workspace._handoff_owner_token(generation),
            )
            with self.assertRaises(RuntimeError):
                google_workspace_worker.run_worker(
                    handoff_id="gwo_workerfail123",
                    key_path=key_path,
                )

            self.assertFalse(key_path.parent.exists())
            self.assertFalse(workspace.ACTIVE_HANDOFF_PATH.exists())

    def test_cleanup_refuses_path_outside_exact_handoff_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            outside = Path(tmp) / "gwo_outside123"
            outside.mkdir()
            key = outside / "private.pem"
            key.write_text("do not remove", encoding="utf-8")

            workspace._cleanup_worker_state(key)

            self.assertTrue(key.exists())

    def test_local_dev_token_is_not_forwarded_through_systemd_argv(self) -> None:
        with mock.patch.object(workspace.shutil, "which", return_value="/usr/bin/systemd-run"):
            used = workspace._start_worker_with_systemd(
                handoff_id="gwo_systemd123",
                key_path=Path("/safe/private.pem"),
                package_dir=REPO_ROOT,
                env={
                    "HOME": "/tmp/home",
                    "TINYHAT_LOCAL_DEV_TOKEN": "must-not-enter-argv",
                },
            )

        self.assertFalse(used)

    def test_worker_command_contains_no_secret_or_generation(self) -> None:
        command = workspace._worker_command(
            handoff_id="gwo_command123",
            key_path=Path("/safe/private.pem"),
            package_dir=REPO_ROOT,
        )
        serialized = " ".join(command)

        self.assertNotIn("generation", serialized)
        self.assertNotIn("client_secret", serialized)
        self.assertNotIn("access_token", serialized)
        self.assertNotIn("refresh_token", serialized)

    def test_package_sources_do_not_reference_runtime_feature_changes(self) -> None:
        package_sources = [
            REPO_ROOT / "google_workspace.py",
            REPO_ROOT / "google_workspace_worker.py",
            REPO_ROOT / "tools.py",
            REPO_ROOT / "context.py",
        ]
        serialized = "\n".join(path.read_text(encoding="utf-8") for path in package_sources)

        self.assertNotIn("hermes_agent", serialized)
        self.assertNotIn("runtimes/openclaw", serialized)
        self.assertNotIn("runtime patch", serialized.lower())
        self.assertNotIn("TINYHAT_GOOGLE_WORKSPACE_OAUTH_CLIENT", serialized)


if __name__ == "__main__":
    unittest.main()
