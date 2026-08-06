"""Tests for value-blind Computer-local Hat secret storage."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))

from tinyhat import hat_secrets, secret_handoff  # noqa: E402


class HatSecretStoreTests(unittest.TestCase):
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
            },
            "PRIVATE",
            hat_handle="acme/hats/forecasting",
        )
        self.assertIn("EXA_API_KEY", message)

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
        self.assertEqual(stored["secrets"]["EXA_API_KEY"], second_value)
        self.assertTrue(removed["removed"])
        self.assertEqual(after["names"], [])
        self.assertEqual(store_mode, 0o600)
        public_shapes = json.dumps([created, updated, listed, removed, after])
        self.assertNotIn(first_value, public_shapes)
        self.assertNotIn(second_value, public_shapes)

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


if __name__ == "__main__":
    unittest.main()
