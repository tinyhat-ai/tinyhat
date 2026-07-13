"""Focused tests for the bounded Tinyhat Google Workspace app bridge.

Usage (unittest, from project root):
    python3 -m unittest test.test_google_workspace_app -v
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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

from tinyhat import google_workspace, google_workspace_app, schemas, tools  # noqa: E402


def fake_open_binary(path: str, *, fd: int | None = None):
    return contextlib.nullcontext(SimpleNamespace(proc_path=path, fd=fd))


def invoke_without_assignment_guard(**kwargs):
    return google_workspace_app._invoke_gws(**kwargs)


def credentials(
    *,
    expires_at: str = "2030-01-01T00:00:00+00:00",
    bundle: str = google_workspace.GOOGLE_RECOMMENDED_CAPABILITY_BUNDLE,
    scopes: list[str] | None = None,
    connection_id: str = "gwo_connection123",
    google_subject: str = "google-user-123",
    email: str = "owner@example.com",
    access_token: str = "test-access-value",
) -> dict[str, object]:
    return {
        "schema": "tinyhat_google_workspace_credentials_v1",
        "tinyhat_connection_id": connection_id,
        "capability_bundle": bundle,
        "services": list(
            ["identity", "tasks", "admin"]
            if bundle == google_workspace.GOOGLE_CUSTOM_CAPABILITY_BUNDLE
            else google_workspace.GOOGLE_REQUESTED_SERVICES
        ),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "central-client.apps.googleusercontent.com",
        "access_token": access_token,
        "refresh_token": "test-refresh-value",
        "token_type": "Bearer",
        "expires_at": expires_at,
        "scopes": list(scopes or google_workspace.GOOGLE_REQUESTED_SCOPES),
        "google_subject": google_subject,
        "email": email,
        "email_verified": True,
        "tinyhat_assignment_binding": "assignment-binding-123",
        "connected_at": "2026-07-10T20:00:00+00:00",
    }


class FakeHermesContext:
    def __init__(self) -> None:
        self.tools: dict[str, dict] = {}

    def register_tool(self, **kwargs) -> None:
        self.tools[kwargs["name"]] = kwargs

    def register_skill(self, *_args, **_kwargs) -> None:
        return None

    def register_command(self, *_args, **_kwargs) -> None:
        return None

    def register_hook(self, *_args, **_kwargs) -> None:
        return None


def write_executable(root: Path, source: str) -> Path:
    path = root / "fake-gws"
    path.write_text("#!/usr/bin/env python3\n" + source, encoding="utf-8")
    path.chmod(0o700)
    return path


class GoogleWorkspaceAppTests(unittest.TestCase):
    def test_adapter_registers_only_generic_app_schema(self) -> None:
        ctx = FakeHermesContext()

        tinyhat.register(ctx)

        self.assertNotIn("tinyhat_gmail_read", ctx.tools)
        self.assertIs(
            ctx.tools["tinyhat_google_workspace_app"]["handler"],
            tools.google_workspace_app,
        )
        schema = schemas.TINYHAT_GOOGLE_WORKSPACE_APP_SCHEMA
        self.assertEqual(ctx.tools["tinyhat_google_workspace_app"]["schema"], schema)
        self.assertEqual(schema["required"], ["argv", "effect"])
        self.assertEqual(
            set(schema["properties"]),
            {"argv", "effect", "confirmed", "confirmation_id", "account_id"},
        )
        self.assertEqual(schema["properties"]["argv"]["maxItems"], 64)

    def test_rejects_malformed_or_unbounded_argv_before_credentials(self) -> None:
        invalid_values = (
            None,
            "schema service.method",
            [],
            ["schema", 1],
            ["schema", ""],
            ["schema", "x" * 4097],
            ["schema", "bad\nvalue"],
            ["schema", "bad\u202evalue"],
            ["schema", *("x" for _ in range(64))],
        )
        with mock.patch.object(
            google_workspace_app,
            "load_verified_google_workspace_credentials",
        ) as load:
            for value in invalid_values:
                with self.subTest(value=type(value).__name__):
                    result = json.loads(tools.google_workspace_app({"argv": value}))
                    self.assertEqual(result["error"], "invalid_parameter")
            load.assert_not_called()

    def test_blocks_auth_process_and_file_modes_but_allows_api_and_future_namespaces(
        self,
    ) -> None:
        blocked = (
            ["gws", "schema"],
            ["--help"],
            ["auth"],
            ["auth", "setup"],
            ["auth", "login"],
            ["auth", "export", "--unmasked"],
            ["setup"],
            ["login"],
            ["export"],
            ["mcp"],
            ["future-service", "resource", "list", "--page-all"],
            ["future-service", "resource", "list", "--page-all=true"],
            ["future-service", "resource", "get", "--output", "/tmp/value"],
            ["future-service", "resource", "get", "--output=/tmp/value"],
            ["future-service", "resource", "get", "-o/tmp/value"],
            ["future-service", "resource", "create", "--upload", "/etc/passwd"],
            ["future-service", "resource", "create", "--upload-content-type=text/plain"],
            ["future-service", "resource", "get", "--sanitize=projects/example/template"],
            ["gmail", "+send", "--attach", "/etc/passwd"],
            ["gmail", "+send", "--attach=/etc/passwd"],
            ["gmail", "+send", "-a", "/etc/passwd"],
            ["gmail", "+send", "-a/etc/passwd"],
        )
        for argv in blocked:
            with self.subTest(argv=argv):
                result = json.loads(tools.google_workspace_app({"argv": argv}))
                self.assertEqual(result["error"], "blocked_command")

        self.assertEqual(
            google_workspace_app._normalize_argv(
                ["drive", "files", "export", "--params", '{"fileId":"safe-id"}']
            ),
            ["drive", "files", "export", "--params", '{"fileId":"safe-id"}'],
        )
        self.assertEqual(
            google_workspace_app._normalize_argv(
                ["future-service", "resource", "list", "--params", "{}"]
            ),
            ["future-service", "resource", "list", "--params", "{}"],
        )
        self.assertEqual(
            google_workspace_app._normalize_argv(
                ["gmail", "+send", "--draft"]
            ),
            ["gmail", "+send", "--draft"],
        )

    def test_child_receives_only_access_token_and_output_is_redacted(self) -> None:
        script = """
import json
import os
import sys
payload = {
    "token": os.environ.get("GOOGLE_WORKSPACE_CLI_TOKEN"),
    "client_secret": os.environ.get("GOOGLE_WORKSPACE_CLI_CLIENT_SECRET"),
    "credentials_file": os.environ.get("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"),
    "adc": os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
    "home": os.environ.get("HOME"),
    "argv": sys.argv[1:],
}
print(json.dumps(payload, sort_keys=True))
print("Bearer " + os.environ["GOOGLE_WORKSPACE_CLI_TOKEN"], file=sys.stderr)
"""
        with tempfile.TemporaryDirectory() as tmp:
            binary = write_executable(Path(tmp), script)
            side_effect = Path(tmp) / "must-not-exist"
            argv = [
                "drive",
                "files",
                "get",
                "--params",
                '{"fileId":"safe-id"}',
                f";touch {side_effect}",
                "$(id)",
            ]
            parent_env = {
                "GOOGLE_WORKSPACE_CLI_TOKEN": "parent-token",
                "GOOGLE_WORKSPACE_CLI_CLIENT_SECRET": "parent-client-secret",
                "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE": "/private/credentials.json",
                "GOOGLE_APPLICATION_CREDENTIALS": "/private/adc.json",
            }
            with (
                mock.patch.dict(os.environ, parent_env, clear=False),
                mock.patch.object(
                    google_workspace_app,
                    "load_verified_google_workspace_credentials",
                    return_value=credentials(),
                ),
                mock.patch.object(
                    google_workspace_app,
                    "_open_trusted_gws_binary",
                    return_value=fake_open_binary(str(binary)),
                ),
                mock.patch.object(
                    google_workspace_app,
                    "_invoke_with_assignment_guard",
                    side_effect=invoke_without_assignment_guard,
                ),
            ):
                result = json.loads(
                    tools.google_workspace_app({"argv": argv, "effect": "read"})
                )
                self.assertEqual(os.environ["GOOGLE_WORKSPACE_CLI_TOKEN"], "parent-token")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["output"]["token"], "[REDACTED]")
        self.assertIsNone(result["output"]["client_secret"])
        self.assertIsNone(result["output"]["credentials_file"])
        self.assertIsNone(result["output"]["adc"])
        self.assertEqual(result["output"]["home"], "[PRIVATE_PATH]")
        self.assertEqual(result["output"]["argv"], argv)
        self.assertEqual(result["stderr"], "Bearer [REDACTED]")
        self.assertTrue(result["content_is_untrusted"])
        self.assertFalse(side_effect.exists())
        serialized = json.dumps(result)
        for forbidden in (
            "test-access-value",
            "test-refresh-value",
            "parent-client-secret",
            "/private/credentials.json",
            "/private/adc.json",
            "tinyhat-gws-",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_near_expiry_refreshes_before_one_gws_invocation(self) -> None:
        expiring = credentials(
            expires_at=(datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        )
        refreshed = credentials()
        refreshed["access_token"] = "new-access-value"
        process = google_workspace_app.AppProcessResult(0, '{"ok":true}', "")
        with (
            mock.patch.object(
                google_workspace_app,
                "load_verified_google_workspace_credentials",
                return_value=expiring,
            ),
            mock.patch.object(
                google_workspace_app,
                "refresh_verified_google_workspace_credentials",
                return_value=refreshed,
            ) as refresh,
            mock.patch.object(
                google_workspace_app,
                "_open_trusted_gws_binary",
                return_value=fake_open_binary("/proc/self/fd/123", fd=123),
            ),
            mock.patch.object(
                google_workspace_app,
                "_invoke_with_assignment_guard",
                return_value=process,
            ) as invoke,
        ):
            result = google_workspace_app.run_google_workspace_app(argv=["schema", "future"])

        self.assertTrue(result["refreshed"])
        refresh.assert_called_once_with()
        self.assertEqual(invoke.call_args.kwargs["credentials"]["access_token"], "new-access-value")

    def test_auth_exit_refreshes_and_retries_once(self) -> None:
        refreshed = credentials()
        refreshed["access_token"] = "new-access-value"
        with (
            mock.patch.object(
                google_workspace_app,
                "load_verified_google_workspace_credentials",
                return_value=credentials(),
            ),
            mock.patch.object(
                google_workspace_app,
                "refresh_verified_google_workspace_credentials",
                return_value=refreshed,
            ) as refresh,
            mock.patch.object(
                google_workspace_app,
                "_open_trusted_gws_binary",
                return_value=fake_open_binary("/proc/self/fd/123", fd=123),
            ),
            mock.patch.object(
                google_workspace_app,
                "_invoke_with_assignment_guard",
                side_effect=[
                    google_workspace_app.AppProcessResult(2, '{"error":"auth"}', ""),
                    google_workspace_app.AppProcessResult(0, '{"ok":true}', ""),
                ],
            ) as invoke,
        ):
            result = google_workspace_app.run_google_workspace_app(argv=["schema", "future"])

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["refreshed"])
        self.assertEqual(invoke.call_count, 2)
        refresh.assert_called_once_with()

    def test_second_auth_exit_stops_without_another_oauth_flow(self) -> None:
        with (
            mock.patch.object(
                google_workspace_app,
                "load_verified_google_workspace_credentials",
                return_value=credentials(),
            ),
            mock.patch.object(
                google_workspace_app,
                "refresh_verified_google_workspace_credentials",
                return_value=credentials(),
            ) as refresh,
            mock.patch.object(
                google_workspace_app,
                "_open_trusted_gws_binary",
                return_value=fake_open_binary("/proc/self/fd/123", fd=123),
            ),
            mock.patch.object(
                google_workspace_app,
                "_invoke_with_assignment_guard",
                side_effect=[
                    google_workspace_app.AppProcessResult(2, "", ""),
                    google_workspace_app.AppProcessResult(2, "", ""),
                ],
            ) as invoke,
        ):
            result = google_workspace_app.run_google_workspace_app(argv=["schema", "future"])

        self.assertEqual(result["error"], "authorization_expired")
        self.assertIn("do not run gws auth", result["message"].lower())
        self.assertEqual(invoke.call_count, 2)
        refresh.assert_called_once_with()

    def test_process_timeout_and_output_overflow_return_no_partial_data(self) -> None:
        script = """
import sys
import time
if sys.argv[1] == "hang":
    time.sleep(5)
else:
    print("x" * 8192)
"""
        with tempfile.TemporaryDirectory() as tmp:
            binary = write_executable(Path(tmp), script)
            started = time.monotonic()
            timed_out = google_workspace_app._run_bounded_process(
                binary=str(binary),
                argv=["hang"],
                access_token="short-token",
                secrets_to_redact=("short-token",),
                limits=google_workspace_app.AppProcessLimits(
                    timeout_seconds=0.05,
                    output_limit_bytes=256,
                ),
            )
            elapsed = time.monotonic() - started
            overflow = google_workspace_app._run_bounded_process(
                binary=str(binary),
                argv=["overflow"],
                access_token="short-token",
                secrets_to_redact=("short-token",),
                limits=google_workspace_app.AppProcessLimits(
                    timeout_seconds=1,
                    output_limit_bytes=256,
                ),
            )

        self.assertTrue(timed_out.timed_out)
        self.assertEqual(timed_out.stdout, "")
        self.assertLess(elapsed, 2)
        self.assertTrue(overflow.output_limited)
        self.assertEqual(overflow.stdout, "")
        self.assertEqual(overflow.stderr, "")

    def test_write_requires_separate_account_and_exact_argv_confirmation(self) -> None:
        argv = [
            "gmail",
            "+send",
            "--to",
            "owner@example.com",
            "--subject",
            "Hello",
            "--body",
            "Body",
        ]
        with mock.patch.object(
            google_workspace_app,
            "load_verified_google_workspace_credentials",
            return_value=credentials(),
        ) as load:
            first = json.loads(
                tools.google_workspace_app({"argv": argv, "effect": "write"})
            )
            confirmation_id = first["expected"]["confirmation_id"]
            changed = json.loads(
                tools.google_workspace_app(
                    {
                        "argv": [*argv[:-1], "Changed body"],
                        "effect": "write",
                        "confirmed": True,
                        "confirmation_id": confirmation_id,
                    }
                )
            )
            self.assertEqual(load.call_count, 2)

        self.assertEqual(first["error"], "confirmation_required")
        self.assertEqual(changed["error"], "confirmation_required")
        self.assertNotEqual(changed["expected"]["confirmation_id"], confirmation_id)
        self.assertEqual(first["example_call"]["account_id"], "gwo_connection123")

    def test_write_confirmation_is_bound_to_the_selected_account(self) -> None:
        argv = [
            "gmail",
            "+send",
            "--to",
            "recipient@example.com",
            "--subject",
            "Hello",
            "--body",
            "Body",
        ]
        def load(account_id: str | None = None):
            return credentials(connection_id=account_id or "gwo_connection123")

        with mock.patch.object(
            google_workspace_app,
            "load_verified_google_workspace_credentials",
            side_effect=load,
        ):
            first = json.loads(
                tools.google_workspace_app(
                    {
                        "argv": argv,
                        "effect": "write",
                        "account_id": "gwo_connection123",
                    }
                )
            )
            confirmation_id = first["expected"]["confirmation_id"]
            switched = json.loads(
                tools.google_workspace_app(
                    {
                        "argv": argv,
                        "effect": "write",
                        "account_id": "gwo_personal456",
                        "confirmed": True,
                        "confirmation_id": confirmation_id,
                    }
                )
            )

        self.assertEqual(switched["error"], "confirmation_required")
        self.assertNotEqual(switched["expected"]["confirmation_id"], confirmation_id)
        self.assertEqual(switched["example_call"]["account_id"], "gwo_personal456")

    def test_sole_account_write_confirmation_cannot_authorize_replacement(self) -> None:
        argv = [
            "gmail",
            "+send",
            "--to",
            "recipient@example.com",
            "--subject",
            "Hello",
            "--body",
            "Body",
        ]
        with mock.patch.object(
            google_workspace_app,
            "load_verified_google_workspace_credentials",
            side_effect=[
                credentials(connection_id="gwo_connection123"),
                credentials(
                    connection_id="gwo_replacement789",
                    google_subject="google-user-789",
                    email="replacement@example.com",
                ),
            ],
        ):
            first = json.loads(
                tools.google_workspace_app({"argv": argv, "effect": "write"})
            )
            replay = json.loads(
                tools.google_workspace_app(
                    {
                        "argv": argv,
                        "effect": "write",
                        "confirmed": True,
                        "confirmation_id": first["expected"]["confirmation_id"],
                    }
                )
            )

        self.assertEqual(replay["error"], "confirmation_required")
        self.assertEqual(replay["example_call"]["account_id"], "gwo_replacement789")
        self.assertNotEqual(
            replay["expected"]["confirmation_id"],
            first["expected"]["confirmation_id"],
        )

    def test_write_confirmation_cannot_replay_after_same_connection_changes(self) -> None:
        argv = [
            "gmail",
            "+send",
            "--to",
            "recipient@example.com",
            "--subject",
            "Hello",
            "--body",
            "Body",
        ]
        initial = credentials(connection_id="gwo_connection123")
        replacement = dict(initial)
        replacement["connected_at"] = "2026-07-11T21:00:00+00:00"
        replacement["capability_bundle"] = (
            google_workspace.GOOGLE_GMAIL_SEND_CAPABILITY_BUNDLE
        )
        replacement["scopes"] = list(google_workspace.GOOGLE_GMAIL_SEND_SCOPES)
        with mock.patch.object(
            google_workspace_app,
            "load_verified_google_workspace_credentials",
            side_effect=[initial, replacement],
        ):
            first = json.loads(
                tools.google_workspace_app({"argv": argv, "effect": "write"})
            )
            replay = json.loads(
                tools.google_workspace_app(
                    {
                        "argv": argv,
                        "effect": "write",
                        "confirmed": True,
                        "confirmation_id": first["expected"]["confirmation_id"],
                    }
                )
            )

        self.assertEqual(replay["error"], "confirmation_required")
        self.assertNotEqual(
            replay["expected"]["confirmation_id"],
            first["expected"]["confirmation_id"],
        )

    def test_multi_account_write_without_selector_fails_before_confirmation(self) -> None:
        accounts = [
            {"account_id": "gwo_connection123", "email": "work@example.com"},
            {"account_id": "gwo_personal456", "email": "personal@example.com"},
        ]
        with (
            mock.patch.object(
                google_workspace_app,
                "load_verified_google_workspace_credentials",
                side_effect=google_workspace.GoogleWorkspaceAccountSelectionRequired(accounts),
            ),
            mock.patch.object(google_workspace_app, "_open_trusted_gws_binary") as open_binary,
        ):
            result = json.loads(
                tools.google_workspace_app(
                    {
                        "argv": ["gmail", "+send", "--to", "owner@example.com"],
                        "effect": "write",
                    }
                )
            )

        self.assertEqual(result["error"], "account_selection_required")
        self.assertEqual(result["accounts"], accounts)
        self.assertNotIn("confirmation_id", json.dumps(result))
        open_binary.assert_not_called()

    def test_app_bridge_reports_safe_account_selection_without_guessing(self) -> None:
        accounts = [
            {
                "account_id": "gwo_connection123",
                "email": "work@example.com",
                "profile": "workspace_readonly",
            },
            {
                "account_id": "gwo_personal456",
                "email": "personal@example.com",
                "profile": "workspace_readonly",
            },
        ]
        with (
            mock.patch.object(
                google_workspace_app,
                "_open_trusted_gws_binary",
                return_value=fake_open_binary("/proc/self/fd/123", fd=123),
            ),
            mock.patch.object(
                google_workspace_app,
                "load_verified_google_workspace_credentials",
                side_effect=google_workspace.GoogleWorkspaceAccountSelectionRequired(accounts),
            ),
        ):
            result = json.loads(
                tools.google_workspace_app(
                    {"argv": ["schema", "future"], "effect": "read"}
                )
            )

        self.assertEqual(result["error"], "account_selection_required")
        self.assertEqual(result["accounts"], accounts)
        self.assertNotIn("token", json.dumps(result))

    def test_app_bridge_loads_only_the_selected_account(self) -> None:
        process = google_workspace_app.AppProcessResult(0, '{"ok":true}', "")
        with (
            mock.patch.object(
                google_workspace_app,
                "load_verified_google_workspace_credentials",
                return_value=credentials(connection_id="gwo_personal456"),
            ) as load,
            mock.patch.object(
                google_workspace_app,
                "_open_trusted_gws_binary",
                return_value=fake_open_binary("/proc/self/fd/123", fd=123),
            ),
            mock.patch.object(
                google_workspace_app,
                "_invoke_with_assignment_guard",
                return_value=process,
            ) as invoke,
        ):
            result = google_workspace_app.run_google_workspace_app(
                argv=["schema", "future"],
                account_id="gwo_personal456",
            )

        load.assert_called_once_with("gwo_personal456")
        self.assertEqual(invoke.call_args.kwargs["account_id"], "gwo_personal456")
        self.assertEqual(result["account_id"], "gwo_personal456")

    def test_unknown_or_mutating_command_cannot_claim_read_effect(self) -> None:
        variants = (
            ["gmail", "users", "messages", "batchUpdate"],
            ["gmail", "users", "messages", "archive"],
            ["drive", "+upload", "/root/secret"],
            ["generate-skills"],
        )
        with mock.patch.object(
            google_workspace_app,
            "load_verified_google_workspace_credentials",
        ) as load:
            for argv in variants:
                with self.subTest(argv=argv):
                    result = json.loads(
                        tools.google_workspace_app({"argv": argv, "effect": "read"})
                    )
                    self.assertIn(result["error"], {"write_effect_required", "blocked_command"})
            load.assert_not_called()

    def test_assignment_change_after_process_discards_output_and_local_credentials(self) -> None:
        current = credentials()
        with (
            mock.patch.object(
                google_workspace_app,
                "_lifecycle_lock",
                return_value=contextlib.nullcontext(),
            ),
            mock.patch.object(
                google_workspace_app,
                "_read_credentials",
                return_value=current,
            ),
            mock.patch.object(
                google_workspace_app,
                "build_platform_client",
                return_value=(mock.Mock(), "local_dev"),
            ),
            mock.patch.object(
                google_workspace_app,
                "_assignment_binding_matches_platform",
                side_effect=[True, False],
            ),
            mock.patch.object(
                google_workspace_app,
                "_invoke_gws",
                return_value=google_workspace_app.AppProcessResult(
                    0, '{"private":"must-discard"}', ""
                ),
            ),
            mock.patch.object(
                google_workspace_app,
                "_cancel_all_pending_handoffs_locked",
            ),
            mock.patch.object(
                google_workspace_app,
                "_delete_credentials_locked",
            ) as delete,
            self.assertRaises(google_workspace_app.GoogleWorkspaceAppError) as raised,
        ):
            google_workspace_app._invoke_with_assignment_guard(
                binary="/proc/self/fd/123",
                binary_fd=123,
                argv=["calendar", "events", "list"],
                credentials=current,
            )

        self.assertEqual(raised.exception.code, "assignment_changed")
        delete.assert_called_once_with()


class GoogleRefreshTransportTests(unittest.TestCase):
    @contextlib.contextmanager
    def _patched_state(self, root: Path):
        state = root / "google-workspace"
        paths = {
            "STATE_DIR": state,
            "CREDENTIALS_PATH": state / "credentials.json",
            "LEGACY_CREDENTIALS_PATH": state / "legacy-credentials.json",
            "HANDOFFS_DIR": state / "handoffs",
            "INSTALL_RECEIPTS_DIR": state / "install-receipts",
            "ACTIVE_HANDOFF_PATH": state / "active-handoff.json",
            "LIFECYCLE_LOCK_PATH": state / "lifecycle.lock",
        }
        with contextlib.ExitStack() as stack:
            for name, value in paths.items():
                stack.enter_context(mock.patch.object(google_workspace, name, value))
            yield

    def test_refresh_uses_encrypted_platform_broker_and_updates_only_tokens(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.posts: list[tuple[str, dict[str, object]]] = []

            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                self.posts.append((path, payload))
                return {"ciphertext_payload": {"algorithm": "RSA-OAEP-256"}}

            def get_json(self, path: str) -> dict[str, object]:
                self.last_get = path
                return {"tinyhat_assignment_binding": "assignment-binding-123"}

        client = Client()
        refresh_document = {
            "schema": "tinyhat_google_workspace_refresh_v1",
            "tinyhat_connection_id": "gwo_connection123",
            "access_token": "new-access-value",
            "refresh_token": "rotated-refresh-value",
            "token_type": "Bearer",
            "expires_at": "2030-01-01T01:00:00+00:00",
            "scopes": list(google_workspace.GOOGLE_REQUESTED_SCOPES),
            "tinyhat_assignment_binding": "assignment-binding-123",
        }
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            initial = google_workspace._normalize_saved_credentials(credentials())
            google_workspace._atomic_save_credentials(initial)
            with (
                mock.patch.object(
                    google_workspace,
                    "load_verified_google_workspace_credentials",
                    return_value=dict(initial),
                ),
                mock.patch.object(
                    google_workspace,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    google_workspace,
                    "_generate_key_pair",
                    return_value=("one-time-private-key", "one-time-public-key"),
                ),
                mock.patch.object(
                    google_workspace,
                    "_decrypt_ciphertext",
                    return_value=json.dumps(refresh_document),
                ),
            ):
                updated = google_workspace.refresh_verified_google_workspace_credentials()

            saved = json.loads(google_workspace.CREDENTIALS_PATH.read_text())["accounts"][0]

        path, payload = client.posts[0]
        self.assertTrue(path.endswith("/google-workspace-oauth/v1/refresh"))
        self.assertEqual(payload["public_key_pem"], "one-time-public-key")
        self.assertEqual(payload["key_algorithm"], "RSA-OAEP-256")
        self.assertEqual(payload["tinyhat_connection_id"], "gwo_connection123")
        self.assertNotIn("client_secret", payload)
        self.assertEqual(updated["access_token"], "new-access-value")
        self.assertEqual(saved["refresh_token"], "rotated-refresh-value")
        self.assertEqual(saved["email"], "owner@example.com")

    def test_refresh_updates_only_the_selected_account(self) -> None:
        class Client:
            def post_json(self, _path: str, _payload: dict[str, object]) -> dict[str, object]:
                return {"ciphertext_payload": {"algorithm": "RSA-OAEP-256"}}

            def get_json(self, _path: str) -> dict[str, object]:
                return {"tinyhat_assignment_binding": "assignment-binding-123"}

        refresh_document = {
            "schema": "tinyhat_google_workspace_refresh_v1",
            "tinyhat_connection_id": "gwo_connection123",
            "access_token": "refreshed-work-token",
            "refresh_token": "rotated-work-refresh",
            "token_type": "Bearer",
            "expires_at": "2030-01-01T01:00:00+00:00",
            "scopes": list(google_workspace.GOOGLE_REQUESTED_SCOPES),
            "tinyhat_assignment_binding": "assignment-binding-123",
        }
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            work = google_workspace._normalize_saved_credentials(credentials())
            personal = google_workspace._normalize_saved_credentials(
                credentials(
                    connection_id="gwo_personal456",
                    google_subject="google-user-456",
                    email="personal@example.com",
                    access_token="personal-access-value",
                )
            )
            google_workspace._atomic_save_credentials(work)
            google_workspace._atomic_save_credentials(personal)
            with (
                mock.patch.object(
                    google_workspace,
                    "load_verified_google_workspace_credentials",
                    return_value=dict(work),
                ) as load,
                mock.patch.object(
                    google_workspace,
                    "build_platform_client",
                    return_value=(Client(), "local_dev"),
                ),
                mock.patch.object(
                    google_workspace,
                    "_generate_key_pair",
                    return_value=("one-time-private-key", "one-time-public-key"),
                ),
                mock.patch.object(
                    google_workspace,
                    "_decrypt_ciphertext",
                    return_value=json.dumps(refresh_document),
                ),
            ):
                google_workspace.refresh_verified_google_workspace_credentials(
                    "gwo_connection123"
                )
            accounts = {
                item["tinyhat_connection_id"]: item
                for item in google_workspace._read_account_store()
            }

        load.assert_called_once_with("gwo_connection123")
        self.assertEqual(accounts["gwo_connection123"]["access_token"], "refreshed-work-token")
        self.assertEqual(accounts["gwo_personal456"]["access_token"], "personal-access-value")

    def test_refresh_preserves_gmail_send_profile_and_exact_scope_superset(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.posts: list[tuple[str, dict[str, object]]] = []

            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                self.posts.append((path, payload))
                return {"ciphertext_payload": {"algorithm": "RSA-OAEP-256"}}

            def get_json(self, _path: str) -> dict[str, object]:
                return {"tinyhat_assignment_binding": "assignment-binding-123"}

        send_scopes = list(google_workspace.GOOGLE_GMAIL_SEND_SCOPES)
        client = Client()
        refresh_document = {
            "schema": "tinyhat_google_workspace_refresh_v1",
            "tinyhat_connection_id": "gwo_connection123",
            "access_token": "new-send-access-value",
            "token_type": "Bearer",
            "expires_at": "2030-01-01T01:00:00+00:00",
            "scopes": send_scopes,
            "tinyhat_assignment_binding": "assignment-binding-123",
        }
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            initial = google_workspace._normalize_saved_credentials(
                credentials(
                    bundle=google_workspace.GOOGLE_GMAIL_SEND_CAPABILITY_BUNDLE,
                    scopes=send_scopes,
                )
            )
            google_workspace._atomic_save_credentials(initial)
            with (
                mock.patch.object(
                    google_workspace,
                    "load_verified_google_workspace_credentials",
                    return_value=dict(initial),
                ),
                mock.patch.object(
                    google_workspace,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    google_workspace,
                    "_generate_key_pair",
                    return_value=("private", "public"),
                ),
                mock.patch.object(
                    google_workspace,
                    "_decrypt_ciphertext",
                    return_value=json.dumps(refresh_document),
                ),
            ):
                updated = google_workspace.refresh_verified_google_workspace_credentials()

        payload = client.posts[0][1]
        self.assertEqual(
            payload["capability_bundle"],
            google_workspace.GOOGLE_GMAIL_SEND_CAPABILITY_BUNDLE,
        )
        self.assertEqual(payload["requested_scopes"], send_scopes)
        self.assertEqual(updated["scopes"], send_scopes)

    def test_refresh_reconstructs_custom_bundle_services_and_exact_scopes(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.posts: list[tuple[str, dict[str, object]]] = []

            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                self.posts.append((path, payload))
                return {"ciphertext_payload": {"algorithm": "RSA-OAEP-256"}}

            def get_json(self, _path: str) -> dict[str, object]:
                return {"tinyhat_assignment_binding": "assignment-binding-123"}

        custom_scopes = [
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/admin.directory.user.readonly",
            *[
                f"https://www.googleapis.com/auth/tasks.scope{index:02d}"
                for index in range(31)
            ],
        ]
        self.assertEqual(len(custom_scopes), google_workspace.GOOGLE_GRANT_SCOPE_MAX_COUNT)
        custom_services = ["identity", "tasks", "admin"]
        client = Client()
        refresh_document = {
            "schema": "tinyhat_google_workspace_refresh_v1",
            "tinyhat_connection_id": "gwo_connection123",
            "access_token": "new-custom-access-value",
            "token_type": "Bearer",
            "expires_at": "2030-01-01T01:00:00+00:00",
            "scopes": custom_scopes,
            "tinyhat_assignment_binding": "assignment-binding-123",
        }
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            initial = google_workspace._normalize_saved_credentials(
                credentials(
                    bundle=google_workspace.GOOGLE_CUSTOM_CAPABILITY_BUNDLE,
                    scopes=custom_scopes,
                )
            )
            google_workspace._atomic_save_credentials(initial)
            with (
                mock.patch.object(
                    google_workspace,
                    "load_verified_google_workspace_credentials",
                    return_value=dict(initial),
                ),
                mock.patch.object(
                    google_workspace,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    google_workspace,
                    "_generate_key_pair",
                    return_value=("private", "public"),
                ),
                mock.patch.object(
                    google_workspace,
                    "_decrypt_ciphertext",
                    return_value=json.dumps(refresh_document),
                ),
            ):
                updated = google_workspace.refresh_verified_google_workspace_credentials()

        payload = client.posts[0][1]
        self.assertEqual(
            payload["capability_bundle"],
            google_workspace.GOOGLE_CUSTOM_CAPABILITY_BUNDLE,
        )
        self.assertEqual(payload["requested_services"], custom_services)
        self.assertEqual(payload["requested_scopes"], custom_scopes)
        self.assertEqual(updated["services"], custom_services)
        self.assertEqual(updated["scopes"], custom_scopes)

    def test_refresh_preserves_exact_legacy_feed_scopes(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.posts: list[tuple[str, dict[str, object]]] = []

            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                self.posts.append((path, payload))
                return {"ciphertext_payload": {"algorithm": "RSA-OAEP-256"}}

            def get_json(self, _path: str) -> dict[str, object]:
                return {"tinyhat_assignment_binding": "assignment-binding-123"}

        legacy_scopes = [
            "openid",
            "email",
            "profile",
            "https://www.google.com/calendar/feeds",
            "https://www.google.com/m8/feeds",
        ]
        legacy_services = ["identity", "calendar", "people"]
        refresh_document = {
            "schema": "tinyhat_google_workspace_refresh_v1",
            "tinyhat_connection_id": "gwo_connection123",
            "access_token": "new-legacy-feed-access-value",
            "token_type": "Bearer",
            "expires_at": "2030-01-01T01:00:00+00:00",
            "scopes": legacy_scopes,
            "tinyhat_assignment_binding": "assignment-binding-123",
        }
        client = Client()
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            saved_credentials = credentials(
                bundle=google_workspace.GOOGLE_CUSTOM_CAPABILITY_BUNDLE,
                scopes=legacy_scopes,
            )
            saved_credentials["services"] = legacy_services
            initial = google_workspace._normalize_saved_credentials(
                saved_credentials
            )
            google_workspace._atomic_save_credentials(initial)
            with (
                mock.patch.object(
                    google_workspace,
                    "load_verified_google_workspace_credentials",
                    return_value=dict(initial),
                ),
                mock.patch.object(
                    google_workspace,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    google_workspace,
                    "_generate_key_pair",
                    return_value=("private", "public"),
                ),
                mock.patch.object(
                    google_workspace,
                    "_decrypt_ciphertext",
                    return_value=json.dumps(refresh_document),
                ),
            ):
                updated = google_workspace.refresh_verified_google_workspace_credentials()

        payload = client.posts[0][1]
        self.assertEqual(
            payload["capability_bundle"],
            google_workspace.GOOGLE_CUSTOM_CAPABILITY_BUNDLE,
        )
        self.assertEqual(payload["requested_services"], legacy_services)
        self.assertEqual(payload["requested_scopes"], legacy_scopes)
        self.assertEqual(updated["services"], legacy_services)
        self.assertEqual(updated["scopes"], legacy_scopes)

    def test_refresh_does_not_recreate_credentials_deleted_during_callback(self) -> None:
        expected = google_workspace._normalize_saved_credentials(credentials())
        refreshed = google_workspace._normalize_refresh_document(
            {
                "schema": "tinyhat_google_workspace_refresh_v1",
                "tinyhat_connection_id": "gwo_connection123",
                "access_token": "new-access-value",
                "token_type": "Bearer",
                "expires_at": "2030-01-01T01:00:00+00:00",
                "scopes": list(google_workspace.GOOGLE_REQUESTED_SCOPES),
                "tinyhat_assignment_binding": "assignment-binding-123",
            },
            expected_connection_id="gwo_connection123",
            expected_assignment_binding="assignment-binding-123",
        )
        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            with self.assertRaises(google_workspace.GoogleWorkspaceError):
                google_workspace._persist_refreshed_credentials(
                    expected=expected,
                    refreshed=refreshed,
                    client=mock.Mock(),
                    platform_auth="local_dev",
                )
            self.assertFalse(google_workspace.CREDENTIALS_PATH.exists())

    def test_refresh_started_before_upgrade_cannot_overwrite_upgraded_access(self) -> None:
        class Client:
            def get_json(self, _path: str) -> dict[str, object]:
                return {"tinyhat_assignment_binding": "assignment-binding-123"}

        gmail_scopes = list(google_workspace.GOOGLE_GMAIL_SEND_SCOPES)
        combined_scopes = list(google_workspace.GOOGLE_GMAIL_SEND_CALENDAR_WRITE_SCOPES)
        expected_before_upgrade = google_workspace._normalize_saved_credentials(
            credentials(
                bundle=google_workspace.GOOGLE_GMAIL_SEND_CAPABILITY_BUNDLE,
                scopes=gmail_scopes,
            )
        )
        stale_refresh = google_workspace._normalize_refresh_document(
            {
                "schema": "tinyhat_google_workspace_refresh_v1",
                "tinyhat_connection_id": "gwo_connection123",
                "access_token": "stale-gmail-only-access",
                "token_type": "Bearer",
                "expires_at": "2030-01-01T01:00:00+00:00",
                "scopes": gmail_scopes,
                "tinyhat_assignment_binding": "assignment-binding-123",
            },
            expected_connection_id="gwo_connection123",
            expected_assignment_binding="assignment-binding-123",
            expected_scopes=gmail_scopes,
        )
        upgraded = google_workspace._normalize_saved_credentials(
            credentials(
                bundle=(google_workspace.GOOGLE_GMAIL_SEND_CALENDAR_WRITE_CAPABILITY_BUNDLE),
                scopes=combined_scopes,
            )
        )
        upgraded["access_token"] = "combined-access"
        upgraded["connected_at"] = "2026-07-10T20:05:00+00:00"

        with tempfile.TemporaryDirectory() as tmp, self._patched_state(Path(tmp)):
            google_workspace._atomic_save_credentials(upgraded)
            before = google_workspace.CREDENTIALS_PATH.read_bytes()

            with self.assertRaises(google_workspace.GoogleWorkspaceError):
                google_workspace._persist_refreshed_credentials(
                    expected=expected_before_upgrade,
                    refreshed=stale_refresh,
                    client=Client(),
                    platform_auth="local_dev",
                )

            after = google_workspace.CREDENTIALS_PATH.read_bytes()
            saved = json.loads(after)["accounts"][0]

        self.assertEqual(after, before)
        self.assertEqual(
            saved["capability_bundle"],
            google_workspace.GOOGLE_GMAIL_SEND_CALENDAR_WRITE_CAPABILITY_BUNDLE,
        )
        self.assertEqual(saved["scopes"], combined_scopes)
        self.assertEqual(saved["access_token"], "combined-access")

    def test_refresh_document_rejects_unknown_or_server_fields(self) -> None:
        document = {
            "schema": "tinyhat_google_workspace_refresh_v1",
            "tinyhat_connection_id": "gwo_connection123",
            "access_token": "new-access-value",
            "token_type": "Bearer",
            "expires_at": "2030-01-01T01:00:00+00:00",
            "scopes": list(google_workspace.GOOGLE_REQUESTED_SCOPES),
            "tinyhat_assignment_binding": "assignment-binding-123",
            "id_token": "must-not-be-accepted",
        }

        with self.assertRaises(google_workspace.GoogleWorkspaceError):
            google_workspace._normalize_refresh_document(
                document,
                expected_connection_id="gwo_connection123",
                expected_assignment_binding="assignment-binding-123",
            )

    def test_refresh_document_rejects_a_different_platform_connection(self) -> None:
        document = {
            "schema": "tinyhat_google_workspace_refresh_v1",
            "tinyhat_connection_id": "gwo_personal456",
            "access_token": "wrong-account-access",
            "token_type": "Bearer",
            "expires_at": "2030-01-01T01:00:00+00:00",
            "scopes": list(google_workspace.GOOGLE_REQUESTED_SCOPES),
            "tinyhat_assignment_binding": "assignment-binding-123",
        }

        with self.assertRaisesRegex(
            google_workspace.GoogleWorkspaceError,
            "account changed",
        ):
            google_workspace._normalize_refresh_document(
                document,
                expected_connection_id="gwo_connection123",
                expected_assignment_binding="assignment-binding-123",
            )

    def test_status_names_the_supported_platform_refresh_mode(self) -> None:
        with mock.patch.object(
            google_workspace,
            "_verified_accounts",
            return_value=([credentials()], "match"),
        ):
            status = google_workspace._status_payload()

        self.assertTrue(status["refresh_token_present"])
        self.assertTrue(status["refresh_supported"])
        self.assertTrue(status["refresh_available"])
        self.assertEqual(status["refresh_mode"], "tinyhat_platform_broker_v1")


if __name__ == "__main__":
    unittest.main()
