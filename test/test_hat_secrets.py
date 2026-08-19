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
from package_support import load_local_tinyhat  # noqa: E402

load_local_tinyhat(REPO_ROOT)

from tinyhat.capabilities.hats import secrets as hat_secrets  # noqa: E402
from tinyhat.capabilities.secrets import handoff as secret_handoff  # noqa: E402
from tinyhat.capabilities.secrets import handoff_worker as secret_handoff_worker  # noqa: E402


class HatSecretStoreTests(unittest.TestCase):
    def test_consumed_hat_resume_reuses_stable_key_and_worker(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.posts: list[tuple[str, dict]] = []

            def post_json(self, path: str, payload: dict) -> dict:
                self.posts.append((path, payload))
                return {
                    "handoff_id": "sh_install",
                    "existing_handoff": True,
                    "hat_handle": "acme/hats/research",
                    "credentials": [{"name": "EXA_API_KEY"}],
                }

        with tempfile.TemporaryDirectory(prefix="tinyhat-consumer-key-") as temp_dir:
            key_path = Path(temp_dir) / "credentials-private.pem"
            key_path.write_text("PRIVATE", encoding="utf-8")
            client = FakeClient()
            with (
                mock.patch.object(
                    secret_handoff,
                    "_hat_credentials_key_pair",
                    return_value=(key_path, "PUBLIC"),
                ) as stable_pair,
                mock.patch.object(
                    secret_handoff,
                    "build_platform_client",
                    return_value=(client, "local_dev"),
                ),
                mock.patch.object(
                    secret_handoff,
                    "_start_worker_process",
                ) as start_worker,
            ):
                result = secret_handoff.start_hat_installation_credentials(
                    installation_id="hti_12345678",
                    hat_handle="acme/hats/research",
                )

        stable_pair.assert_called_once_with("acme/hats/research")
        self.assertEqual(client.posts[0][1]["public_key_pem"], "PUBLIC")
        start_worker.assert_called_once_with(
            {
                "handoff_id": "sh_install",
                "existing_handoff": True,
                "hat_handle": "acme/hats/research",
                "credentials": [{"name": "EXA_API_KEY"}],
            },
            "PRIVATE",
            hat_handle="acme/hats/research",
            persistent=True,
            key_path=key_path,
        )
        self.assertTrue(result["existing_handoff"])

    def test_creator_to_consumer_hat_bundle_is_signed_and_ciphertext_only(
        self,
    ) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.posts: list[tuple[str, dict]] = []

            def post_json(self, path: str, payload: dict) -> dict:
                self.posts.append((path, payload))
                return {"status": "ok"}

        creator_values = {
            "EXA_API_KEY": "creator-exa-private-value",
            "OPENROUTER_API_KEY": "creator-model-private-value",
        }
        consumer_private_key, consumer_public_key = secret_handoff._generate_key_pair()
        credentials = list(creator_values)
        context = {
            "handoff_id": "sh_install_12345678",
            "installation_id": "hti_12345678",
            "hat_handle": "acme/hats/research",
            "credential_names_sha256": (
                hat_secrets.credential_names_fingerprint_sha256(credentials)
            ),
            "consumer_public_key_fingerprint_sha256": (
                hat_secrets.public_key_fingerprint_sha256(consumer_public_key)
            ),
        }
        with (
            tempfile.TemporaryDirectory(prefix="tinyhat-creator-store-") as temp_dir,
            mock.patch.dict(os.environ, {"TINYHAT_HAT_STORE_DIR": temp_dir}),
        ):
            hat_secrets.set_hat_secrets("acme/hats/research", creator_values)
            _creator_private_path, creator_public_key = hat_secrets.ensure_hat_key_pair(
                "acme/hats/research"
            )
            creator_fingerprint = hat_secrets.public_key_fingerprint_sha256(creator_public_key)
            encrypted = hat_secrets.create_authenticated_hat_secret_envelope(
                "acme/hats/research",
                consumer_public_key_pem=consumer_public_key,
                expected_names=credentials,
                context=context,
                expected_creator_public_key_fingerprint_sha256=creator_fingerprint,
            )

        serialized_ciphertext = json.dumps(encrypted, sort_keys=True)
        self.assertNotIn("creator-exa-private-value", serialized_ciphertext)
        self.assertNotIn("creator-model-private-value", serialized_ciphertext)
        self.assertEqual(
            encrypted["schema"],
            "tinyhat_hat_credentials_envelope_v1",
        )

        fake_client = FakeClient()
        with (
            tempfile.TemporaryDirectory(prefix="tinyhat-consumer-store-") as temp_dir,
            mock.patch.dict(os.environ, {"TINYHAT_HAT_STORE_DIR": temp_dir}),
            mock.patch.object(secret_handoff, "_set_hermes_secret") as hermes_save,
            mock.patch.object(secret_handoff, "_register_terminal_env_secret"),
        ):
            installed = secret_handoff._install_hat_installation_credentials_bundle(
                client=fake_client,
                platform_auth="local_dev",
                handoff_id="sh_install_12345678",
                private_key_pem=consumer_private_key,
                state={
                    "hat_handle": "acme/hats/research",
                    "installation_id": "hti_12345678",
                    "creator_public_key_pem": creator_public_key,
                    "creator_public_key_fingerprint_sha256": creator_fingerprint,
                    "consumer_public_key_fingerprint_sha256": context[
                        "consumer_public_key_fingerprint_sha256"
                    ],
                    "credentials": [
                        {"name": "EXA_API_KEY"},
                        {"name": "OPENROUTER_API_KEY"},
                    ],
                    "ciphertext_payload": encrypted,
                },
                hat_handle="acme/hats/research",
            )
            local = hat_secrets.list_hat_secret_names("acme/hats/research")

        self.assertTrue(installed)
        self.assertEqual(local["names"], sorted(creator_values))
        self.assertEqual(hermes_save.call_count, 2)
        self.assertNotIn("creator-", json.dumps(fake_client.posts))
        self.assertEqual(
            fake_client.posts[0][1]["outcome"],
            "installed_restart_pending",
        )

    def test_consumer_rejects_tampered_creator_envelope(self) -> None:
        creator_values = {"EXA_API_KEY": "creator-private-value"}
        consumer_private_key, consumer_public_key = secret_handoff._generate_key_pair()
        context = {
            "handoff_id": "sh_install_12345678",
            "installation_id": "hti_12345678",
            "hat_handle": "acme/hats/research",
            "credential_names_sha256": (
                hat_secrets.credential_names_fingerprint_sha256(["EXA_API_KEY"])
            ),
            "consumer_public_key_fingerprint_sha256": (
                hat_secrets.public_key_fingerprint_sha256(consumer_public_key)
            ),
        }
        with (
            tempfile.TemporaryDirectory(prefix="tinyhat-creator-store-") as temp_dir,
            mock.patch.dict(os.environ, {"TINYHAT_HAT_STORE_DIR": temp_dir}),
        ):
            hat_secrets.set_hat_secrets("acme/hats/research", creator_values)
            _creator_private_path, creator_public_key = hat_secrets.ensure_hat_key_pair(
                "acme/hats/research"
            )
            creator_fingerprint = hat_secrets.public_key_fingerprint_sha256(creator_public_key)
            encrypted = hat_secrets.create_authenticated_hat_secret_envelope(
                "acme/hats/research",
                consumer_public_key_pem=consumer_public_key,
                expected_names=["EXA_API_KEY"],
                context=context,
                expected_creator_public_key_fingerprint_sha256=creator_fingerprint,
            )
        encrypted["context"] = {**context, "installation_id": "hti_other"}

        with self.assertRaisesRegex(
            secret_handoff.SecretHandoffError,
            "creator signature could not be verified",
        ):
            secret_handoff._install_hat_installation_credentials_bundle(
                client=mock.Mock(),
                platform_auth="local_dev",
                handoff_id="sh_install_12345678",
                private_key_pem=consumer_private_key,
                state={
                    "hat_handle": "acme/hats/research",
                    "installation_id": "hti_12345678",
                    "creator_public_key_pem": creator_public_key,
                    "creator_public_key_fingerprint_sha256": creator_fingerprint,
                    "consumer_public_key_fingerprint_sha256": context[
                        "consumer_public_key_fingerprint_sha256"
                    ],
                    "credentials": [{"name": "EXA_API_KEY"}],
                    "ciphertext_payload": encrypted,
                },
                hat_handle="acme/hats/research",
            )

        encrypted["context"] = context
        encrypted["access_token"] = "must-not-be-accepted"
        with self.assertRaisesRegex(
            secret_handoff.SecretHandoffError,
            "creator signature could not be verified",
        ):
            secret_handoff._install_hat_installation_credentials_bundle(
                client=mock.Mock(),
                platform_auth="local_dev",
                handoff_id="sh_install_12345678",
                private_key_pem=consumer_private_key,
                state={
                    "hat_handle": "acme/hats/research",
                    "installation_id": "hti_12345678",
                    "creator_public_key_pem": creator_public_key,
                    "creator_public_key_fingerprint_sha256": creator_fingerprint,
                    "consumer_public_key_fingerprint_sha256": context[
                        "consumer_public_key_fingerprint_sha256"
                    ],
                    "credentials": [{"name": "EXA_API_KEY"}],
                    "ciphertext_payload": encrypted,
                },
                hat_handle="acme/hats/research",
            )

    def test_hat_worker_exits_after_one_bundle_and_keeps_stable_key(self) -> None:
        class FakeClient:
            def get_json(self, _path: str) -> dict:
                return {
                    "status": "submitted",
                    "handoff_kind": "hat_credentials",
                }

        with (
            tempfile.TemporaryDirectory(prefix="tinyhat-hat-worker-") as temp_dir,
            mock.patch.object(
                secret_handoff_worker,
                "build_platform_client",
                return_value=(FakeClient(), "local_dev"),
            ),
            mock.patch.object(
                secret_handoff_worker,
                "_install_submitted_secret",
                return_value=True,
            ) as install,
        ):
            key_path = Path(temp_dir) / "credentials-private.pem"
            key_path.write_text("PRIVATE", encoding="utf-8")

            secret_handoff_worker.run_worker(
                handoff_id="sh_hat_bundle",
                key_path=key_path,
                hat_handle="acme/hats/forecasting",
                persistent=True,
            )

            self.assertTrue(key_path.exists())

        install.assert_called_once()

    def test_delete_hat_store_removes_values_and_key_pair_only_for_that_hat(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch.dict(
                os.environ,
                {"TINYHAT_HAT_STORE_DIR": temp_dir},
            ),
        ):
            hat_secrets.set_hat_secret(
                "acme/hats/forecasting",
                "EXA_API_KEY",
                "dummy-value",
            )
            hat_directory = hat_secrets.hat_secret_store_path("acme/hats/forecasting").parent
            (hat_directory / "credentials-private.pem").write_text(
                "dummy-private-key",
                encoding="utf-8",
            )
            hat_secrets.set_hat_secret(
                "acme/hats/neighbor",
                "EXA_API_KEY",
                "neighbor-value",
            )

            result = hat_secrets.delete_hat_secret_store("acme/hats/forecasting")

            self.assertTrue(result["removed"])
            self.assertFalse(hat_directory.exists())
            self.assertTrue(hat_secrets.hat_secret_store_path("acme/hats/neighbor").exists())

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
                mock.patch.object(
                    secret_handoff,
                    "list_hat_secret_names",
                    return_value={"names": ["EXA_API_KEY"]},
                ),
            ):
                message = secret_handoff.start_hat_credentials_handoff("forecasting")

        self.assertEqual(len(fake_client.posts), 1)
        request = fake_client.posts[0][1]
        self.assertEqual(request["handoff_kind"], "hat_credentials")
        self.assertEqual(request["hat_identifier"], "acme/hats/forecasting")
        self.assertEqual(request["existing_credential_names"], ["EXA_API_KEY"])
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
            ["/hapi/v1/computers/local-dev/hats/v1/detail?identifier=forecasting"],
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

    def test_listing_absent_store_does_not_create_credential_material(self) -> None:
        with (
            tempfile.TemporaryDirectory(prefix="tinyhat-hat-store-") as temp_dir,
            mock.patch.dict(os.environ, {"TINYHAT_HAT_STORE_DIR": temp_dir}),
        ):
            store_path = hat_secrets.hat_secret_store_path("acme/hats/forecasting")
            result = hat_secrets.list_hat_secret_names("acme/hats/forecasting")

            self.assertEqual(result["names"], [])
            self.assertFalse(store_path.exists())
            self.assertFalse(store_path.with_name("credentials-private.pem").exists())
            self.assertFalse(store_path.with_name("credentials-public.pem").exists())

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

    def test_remove_and_recreate_one_value_preserves_the_other(self) -> None:
        with (
            tempfile.TemporaryDirectory(prefix="tinyhat-hat-store-") as temp_dir,
            mock.patch.dict(os.environ, {"TINYHAT_HAT_STORE_DIR": temp_dir}),
        ):
            hat_secrets.set_hat_secrets(
                "acme/hats/forecasting",
                {
                    "EXA_API_KEY": "exa-local-only",
                    "GITHUB_TOKEN": "github-local-only",
                },
            )
            removed = hat_secrets.remove_hat_secret(
                "acme/hats/forecasting",
                "GITHUB_TOKEN",
            )
            after_remove = hat_secrets.list_hat_secret_names("acme/hats/forecasting")
            recreated = hat_secrets.set_hat_secret(
                "acme/hats/forecasting",
                "GITHUB_TOKEN",
                "github-recreated-local-only",
            )
            after_recreate = hat_secrets.list_hat_secret_names("acme/hats/forecasting")

        self.assertTrue(removed["removed"])
        self.assertEqual(after_remove["names"], ["EXA_API_KEY"])
        self.assertEqual(recreated["operation"], "created")
        self.assertEqual(
            after_recreate["names"],
            ["EXA_API_KEY", "GITHUB_TOKEN"],
        )

    def test_handle_rename_preserves_encrypted_local_values_and_key(self) -> None:
        secret_value = "value-that-must-stay-local"
        with (
            tempfile.TemporaryDirectory(prefix="tinyhat-hat-store-") as temp_dir,
            mock.patch.dict(
                os.environ,
                {"TINYHAT_HAT_STORE_DIR": temp_dir},
            ),
        ):
            hat_secrets.set_hat_secret(
                "acme/hats/forecasting",
                "EXA_API_KEY",
                secret_value,
            )
            old_path = hat_secrets.hat_secret_store_path("acme/hats/forecasting")
            old_private_key = old_path.with_name("credentials-private.pem").read_text(
                encoding="utf-8"
            )

            result = hat_secrets.rename_hat_secret_store(
                "acme/hats/forecasting",
                "acme/hats/executive-forecasting",
            )

            new_path = hat_secrets.hat_secret_store_path("acme/hats/executive-forecasting")
            listed = hat_secrets.list_hat_secret_names("acme/hats/executive-forecasting")
            stored = json.loads(new_path.read_text(encoding="utf-8"))
            new_private_key = new_path.with_name("credentials-private.pem").read_text(
                encoding="utf-8"
            )
            old_exists_after = old_path.exists()

        self.assertTrue(result["renamed"])
        self.assertFalse(old_exists_after)
        self.assertEqual(listed["names"], ["EXA_API_KEY"])
        self.assertEqual(stored["handle"], "acme/hats/executive-forecasting")
        self.assertEqual(old_private_key, new_private_key)
        self.assertNotIn(secret_value, json.dumps(stored))
        self.assertNotIn(secret_value, json.dumps(result))

    def test_legacy_plaintext_store_is_migrated_when_names_are_listed(
        self,
    ) -> None:
        legacy_value = "legacy-plaintext-must-disappear"
        with (
            tempfile.TemporaryDirectory(prefix="tinyhat-hat-store-") as temp_dir,
            mock.patch.dict(
                os.environ,
                {"TINYHAT_HAT_STORE_DIR": temp_dir},
            ),
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

    def test_hat_credentials_partial_update_preserves_saved_values(self) -> None:
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
                "credentials": {"EXA_API_KEY": "replacement-value"},
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
        ):
            hat_secrets.set_hat_secrets(
                "acme/hats/forecasting",
                {
                    "EXA_API_KEY": "old-value",
                    "GITHUB_TOKEN": "keep-value",
                },
            )
            installed = secret_handoff._install_submitted_secret(
                client=fake_client,
                platform_auth="local_dev",
                handoff_id="sh_hat_bundle",
                private_key_pem="PRIVATE",
                state={
                    "handoff_kind": "hat_credentials",
                    "hat_handle": "acme/hats/forecasting",
                    "credentials": [
                        {"name": "EXA_API_KEY", "has_existing_value": True},
                        {"name": "GITHUB_TOKEN", "has_existing_value": True},
                    ],
                    "ciphertext_payload": {"algorithm": "RSA-OAEP-256"},
                },
                hat_handle="acme/hats/forecasting",
            )
            names = hat_secrets.list_hat_secret_names("acme/hats/forecasting")
            payload = hat_secrets._read_store(  # type: ignore[attr-defined]
                hat_secrets.hat_secret_store_path("acme/hats/forecasting"),
                handle="acme/hats/forecasting",
            )
            values = hat_secrets._store_values(  # type: ignore[attr-defined]
                hat_secrets.hat_secret_store_path("acme/hats/forecasting"),
                payload,
                handle="acme/hats/forecasting",
            )

        self.assertTrue(installed)
        self.assertEqual(names["names"], ["EXA_API_KEY", "GITHUB_TOKEN"])
        self.assertEqual(values["EXA_API_KEY"], "replacement-value")
        self.assertEqual(values["GITHUB_TOKEN"], "keep-value")

    def test_hat_credentials_partial_update_rejects_unsaved_blank(self) -> None:
        encrypted_bundle = json.dumps(
            {
                "schema": "tinyhat_hat_credentials_bundle_v1",
                "credentials": {"EXA_API_KEY": "replacement-value"},
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
            self.assertRaisesRegex(
                secret_handoff.SecretHandoffError,
                "omitted a credential without a saved value",
            ),
        ):
            secret_handoff._install_submitted_secret(
                client=mock.Mock(),
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


if __name__ == "__main__":
    unittest.main()
