"""Tests for value-blind Computer-local Hat secret storage."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))

from tinyhat import hat_secrets, secret_handoff  # noqa: E402


class HatSecretStoreTests(unittest.TestCase):
    def test_delete_hat_store_removes_values_and_key_pair_only_for_that_hat(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"TINYHAT_HAT_STORE_DIR": temp_dir},
        ):
            hat_secrets.set_hat_secret(
                "acme/hats/forecasting",
                "EXA_API_KEY",
                "dummy-value",
            )
            hat_directory = hat_secrets.hat_secret_store_path(
                "acme/hats/forecasting"
            ).parent
            (hat_directory / "credentials-private.pem").write_text(
                "dummy-private-key",
                encoding="utf-8",
            )
            hat_secrets.set_hat_secret(
                "acme/hats/neighbor",
                "EXA_API_KEY",
                "neighbor-value",
            )

            result = hat_secrets.delete_hat_secret_store(
                "acme/hats/forecasting"
            )

            self.assertTrue(result["removed"])
            self.assertFalse(hat_directory.exists())
            self.assertTrue(
                hat_secrets.hat_secret_store_path("acme/hats/neighbor").exists()
            )

    def test_hat_bundle_reuses_one_locked_local_key_pair(self) -> None:
        with (
            tempfile.TemporaryDirectory(prefix="tinyhat-hat-key-store-") as temp_dir,
            mock.patch.dict(os.environ, {"TINYHAT_HAT_STORE_DIR": temp_dir}),
            mock.patch.object(
                secret_handoff,
                "_generate_key_pair",
                return_value=("PRIVATE", "PUBLIC"),
            ) as generate,
        ):
            first_path, first_public = secret_handoff._hat_credentials_key_pair(
                "acme/hats/forecasting"
            )
            second_path, second_public = secret_handoff._hat_credentials_key_pair(
                "acme/hats/forecasting"
            )

            self.assertEqual(first_path, second_path)
            self.assertEqual(first_public, "PUBLIC")
            self.assertEqual(second_public, "PUBLIC")
            self.assertEqual(first_path.read_text(encoding="utf-8"), "PRIVATE")
            self.assertEqual(stat.S_IMODE(first_path.stat().st_mode), 0o600)
            self.assertEqual(
                stat.S_IMODE(first_path.with_name("credentials-public.pem").stat().st_mode),
                0o600,
            )
            generate.assert_called_once_with()

    def test_hat_bundle_handoff_sends_one_button_and_keeps_key_local(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.posts: list[tuple[str, dict]] = []

            def get_json(self, path: str) -> dict:
                if "/detail?" in path:
                    return {"handle": "acme/hats/forecasting"}
                return {
                    "credentials": [
                        {"name": "EXA_API_KEY", "description": "Research"},
                        {"name": "GITHUB_TOKEN", "description": "Repositories"},
                    ]
                }

            def post_json(self, path: str, payload: dict) -> dict:
                self.posts.append((path, payload))
                return {
                    "handoff_id": "sh_hat_bundle",
                    "hat_handle": "acme/hats/forecasting",
                    "credentials": [
                        {"name": "EXA_API_KEY"},
                        {"name": "GITHUB_TOKEN"},
                    ],
                }

        fake_client = FakeClient()
        with tempfile.TemporaryDirectory(prefix="tinyhat-hat-key-") as temp_dir:
            private_key_path = Path(temp_dir) / "credentials-private.pem"
            private_key_path.write_text("PRIVATE", encoding="utf-8")
            with (
                mock.patch.object(
                    secret_handoff,
                    "build_platform_client",
                    return_value=(fake_client, "local_dev"),
                ),
                mock.patch.object(
                    secret_handoff,
                    "_hat_credentials_key_pair",
                    return_value=(private_key_path, "PUBLIC"),
                ),
                mock.patch.object(
                    secret_handoff,
                    "_start_worker_process",
                ) as start_worker,
            ):
                message = secret_handoff.start_hat_credentials_handoff("forecasting")

        self.assertEqual(len(fake_client.posts), 1)
        request = fake_client.posts[0][1]
        self.assertEqual(request["handoff_kind"], "hat_credentials")
        self.assertEqual(request["hat_identifier"], "acme/hats/forecasting")
        self.assertNotIn("credentials", request)
        start_worker.assert_called_once_with(
            {
                "handoff_id": "sh_hat_bundle",
                "hat_handle": "acme/hats/forecasting",
                "credentials": [
                    {"name": "EXA_API_KEY"},
                    {"name": "GITHUB_TOKEN"},
                ],
            },
            "PRIVATE",
            hat_handle="acme/hats/forecasting",
            persistent=True,
            key_path=private_key_path,
        )
        self.assertIn("one secure Enter credentials button", message)

    def test_hat_handoff_resolves_owner_handle_and_scopes_worker(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.get_paths: list[str] = []
                self.posts: list[tuple[str, dict]] = []

            def get_json(self, path: str) -> dict:
                self.get_paths.append(path)
                return {"handle": "acme/hats/forecasting"}

            def post_json(self, path: str, payload: dict) -> dict:
                self.posts.append((path, payload))
                return {
                    "handoff_id": "sh_hat",
                    "secret_name": "EXA_API_KEY",
                    "hat_handle": "acme/hats/forecasting",
                }

        fake_client = FakeClient()
        with (
            mock.patch.object(
                secret_handoff,
                "_generate_key_pair",
                return_value=("PRIVATE", "PUBLIC"),
            ),
            mock.patch.object(
                secret_handoff,
                "build_platform_client",
                return_value=(fake_client, "local_dev"),
            ),
            mock.patch.object(secret_handoff, "_start_worker_process") as start_worker,
        ):
            message = secret_handoff.start_private_secret_handoff(
                {
                    "name": "EXA_API_KEY",
                    "description": "Research API key",
                    "hat_identifier": "forecasting",
                }
            )

        self.assertEqual(
            fake_client.get_paths,
            ["/hapi/v1/computers/local-dev/hats/v1/detail?" "identifier=forecasting"],
        )
        self.assertEqual(
            fake_client.posts[0][0],
            "/hapi/v1/computers/local-dev/private-secret-handoffs/v1",
        )
        self.assertEqual(
            fake_client.posts[0][1]["hat_identifier"],
            "acme/hats/forecasting",
        )
        self.assertNotIn("value", fake_client.posts[0][1])
        start_worker.assert_called_once_with(
            {
                "handoff_id": "sh_hat",
                "secret_name": "EXA_API_KEY",
                "hat_handle": "acme/hats/forecasting",
            },
            "PRIVATE",
            hat_handle="acme/hats/forecasting",
        )
        self.assertIn("EXA_API_KEY", message)

    def test_unknown_hat_returns_structured_self_correction(self) -> None:
        class FakeClient:
            def get_json(self, _path: str) -> dict:
                raise secret_handoff.PlatformError("not found", status_code=404)

        with (
            mock.patch.object(
                secret_handoff,
                "_generate_key_pair",
                return_value=("PRIVATE", "PUBLIC"),
            ),
            mock.patch.object(
                secret_handoff,
                "build_platform_client",
                return_value=(FakeClient(), "local_dev"),
            ),
        ):
            result = json.loads(
                secret_handoff.start_private_secret_handoff(
                    {
                        "name": "EXA_API_KEY",
                        "description": "Research API key",
                        "hat_identifier": "missing-hat",
                    }
                )
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "hat_not_found")
        self.assertIn("action=list", result["message"])

    def test_existing_handoff_rejects_different_effective_binding(self) -> None:
        class FakeClient:
            def get_json(self, _path: str) -> dict:
                return {"handle": "acme/hats/forecasting"}

            def post_json(self, _path: str, _payload: dict) -> dict:
                return {
                    "handoff_id": "sh_existing",
                    "existing_handoff": True,
                    "secret_name": "EXA_API_KEY",
                    "hat_handle": "acme/hats/different",
                }

        with (
            mock.patch.object(
                secret_handoff,
                "_generate_key_pair",
                return_value=("PRIVATE", "PUBLIC"),
            ),
            mock.patch.object(
                secret_handoff,
                "build_platform_client",
                return_value=(FakeClient(), "local_dev"),
            ),
            mock.patch.object(secret_handoff, "_start_worker_process") as start_worker,
        ):
            result = json.loads(
                secret_handoff.start_private_secret_handoff(
                    {
                        "name": "EXA_API_KEY",
                        "description": "Research API key",
                        "hat_identifier": "forecasting",
                    }
                )
            )

        self.assertEqual(result["error"], "handoff_binding_mismatch")
        start_worker.assert_not_called()

    def test_create_update_remove_stays_local_and_returns_no_values(self) -> None:
        first_value = "first-local-only-value"
        second_value = "rotated-local-only-value"
        with (
            tempfile.TemporaryDirectory(prefix="tinyhat-hat-store-") as temp_dir,
            mock.patch.dict(
                os.environ,
                {"TINYHAT_HAT_STORE_DIR": temp_dir},
            ),
        ):
            created = hat_secrets.set_hat_secret(
                "acme/hats/forecasting",
                "EXA_API_KEY",
                first_value,
            )
            updated = hat_secrets.set_hat_secret(
                "acme/hats/forecasting",
                "EXA_API_KEY",
                second_value,
            )
            listed = hat_secrets.list_hat_secret_names("acme/hats/forecasting")
            store_path = hat_secrets.hat_secret_store_path("acme/hats/forecasting")
            stored = json.loads(store_path.read_text(encoding="utf-8"))
            store_mode = store_path.stat().st_mode & 0o777
            removed = hat_secrets.remove_hat_secret(
                "acme/hats/forecasting",
                "EXA_API_KEY",
            )
            after = hat_secrets.list_hat_secret_names("acme/hats/forecasting")

        self.assertEqual(created["operation"], "created")
        self.assertEqual(updated["operation"], "updated")
        self.assertEqual(listed["names"], ["EXA_API_KEY"])
        self.assertEqual(stored["schema"], "tinyhat_hat_secrets_v2")
        self.assertEqual(stored["names"], ["EXA_API_KEY"])
        self.assertNotIn(first_value, json.dumps(stored))
        self.assertNotIn(second_value, json.dumps(stored))
        self.assertTrue(removed["removed"])
        self.assertEqual(after["names"], [])
        self.assertEqual(store_mode, 0o600)
        public_shapes = json.dumps([created, updated, listed, removed, after])
        self.assertNotIn(first_value, public_shapes)
        self.assertNotIn(second_value, public_shapes)

    def test_legacy_plaintext_store_is_migrated_when_names_are_listed(
        self,
    ) -> None:
        legacy_value = "legacy-plaintext-must-disappear"
        with tempfile.TemporaryDirectory(
            prefix="tinyhat-hat-store-"
        ) as temp_dir, mock.patch.dict(
            os.environ,
            {"TINYHAT_HAT_STORE_DIR": temp_dir},
        ):
            store_path = hat_secrets.hat_secret_store_path("acme/hats/forecasting")
            store_path.parent.mkdir(parents=True, exist_ok=True)
            store_path.write_text(
                json.dumps(
                    {
                        "schema": "tinyhat_hat_secrets_v1",
                        "handle": "acme/hats/forecasting",
                        "secrets": {"EXA_API_KEY": legacy_value},
                    }
                ),
                encoding="utf-8",
            )

            listed = hat_secrets.list_hat_secret_names("acme/hats/forecasting")
            migrated = store_path.read_text(encoding="utf-8")

        self.assertEqual(listed["names"], ["EXA_API_KEY"])
        self.assertIn("tinyhat_hat_secrets_v2", migrated)
        self.assertNotIn(legacy_value, migrated)

    def test_hat_handoff_installs_locally_then_sends_metadata_only(self) -> None:
        secret_value = "plaintext-never-sent-to-platform"

        class FakeClient:
            def __init__(self) -> None:
                self.posts: list[tuple[str, dict]] = []

            def post_json(self, path: str, payload: dict) -> dict:
                self.posts.append((path, payload))
                return {"status": "ok"}

        fake_client = FakeClient()
        with (
            tempfile.TemporaryDirectory(prefix="tinyhat-hat-store-") as temp_dir,
            mock.patch.dict(
                os.environ,
                {"TINYHAT_HAT_STORE_DIR": temp_dir},
            ),
            mock.patch.object(
                secret_handoff,
                "_decrypt_ciphertext",
                return_value=secret_value,
            ),
        ):
            installed = secret_handoff._install_submitted_secret(
                client=fake_client,
                platform_auth="local_dev",
                handoff_id="sh_hat",
                private_key_pem="PRIVATE",
                state={
                    "secret_name": "EXA_API_KEY",
                    "description": "Research API key",
                    "ciphertext_payload": {"algorithm": "RSA-OAEP-256"},
                },
                hat_handle="acme/hats/forecasting",
            )
            local = hat_secrets.list_hat_secret_names("acme/hats/forecasting")

        self.assertTrue(installed)
        self.assertEqual(local["names"], ["EXA_API_KEY"])
        self.assertEqual(
            fake_client.posts[0],
            (
                "/hapi/v1/computers/local-dev/hats/v1/credentials",
                {
                    "identifier": "acme/hats/forecasting",
                    "name": "EXA_API_KEY",
                    "description": "Research API key",
                },
            ),
        )
        self.assertEqual(
            fake_client.posts[1],
            (
                "/hapi/v1/computers/local-dev/private-secret-handoffs/v1/sh_hat/claim",
                {"installed": True, "message": None},
            ),
        )
        self.assertNotIn(secret_value, json.dumps(fake_client.posts))

    def test_hat_credentials_are_installed_atomically_without_restart(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.posts: list[tuple[str, dict]] = []

            def post_json(self, path: str, payload: dict) -> dict:
                self.posts.append((path, payload))
                return {"status": "ok"}

        fake_client = FakeClient()
        encrypted_bundle = json.dumps(
            {
                "schema": "tinyhat_hat_credentials_bundle_v1",
                "credentials": {
                    "EXA_API_KEY": "test-value-one",
                    "GITHUB_TOKEN": "test-value-two",
                },
            }
        )
        with (
            tempfile.TemporaryDirectory(prefix="tinyhat-hat-store-") as temp_dir,
            mock.patch.dict(os.environ, {"TINYHAT_HAT_STORE_DIR": temp_dir}),
            mock.patch.object(
                secret_handoff,
                "_decrypt_ciphertext",
                return_value=encrypted_bundle,
            ),
            mock.patch.object(secret_handoff, "_set_hermes_secret") as hermes_save,
        ):
            installed = secret_handoff._install_submitted_secret(
                client=fake_client,
                platform_auth="local_dev",
                handoff_id="sh_hat_bundle",
                private_key_pem="PRIVATE",
                state={
                    "handoff_kind": "hat_credentials",
                    "hat_handle": "acme/hats/forecasting",
                    "credentials": [
                        {"name": "EXA_API_KEY"},
                        {"name": "GITHUB_TOKEN"},
                    ],
                    "ciphertext_payload": {"algorithm": "RSA-OAEP-256"},
                },
                hat_handle="acme/hats/forecasting",
            )
            local = hat_secrets.list_hat_secret_names("acme/hats/forecasting")

        self.assertTrue(installed)
        self.assertEqual(local["names"], ["EXA_API_KEY", "GITHUB_TOKEN"])
        hermes_save.assert_not_called()
        self.assertEqual(
            fake_client.posts,
            [
                (
                    "/hapi/v1/computers/local-dev/private-secret-handoffs/v1/sh_hat_bundle/claim",
                    {
                        "installed": True,
                        "message": None,
                        "gateway_ready": True,
                    },
                )
            ],
        )
        self.assertNotIn("test-value", json.dumps(fake_client.posts))


if __name__ == "__main__":
    unittest.main()
