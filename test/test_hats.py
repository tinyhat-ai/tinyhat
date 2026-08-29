"""Tests for the Tinyhat shareable-hats plugin tool."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))
from package_support import load_local_tinyhat  # noqa: E402

load_local_tinyhat(REPO_ROOT)

from tinyhat.capabilities.hats import tool as hats_module  # noqa: E402


class FakePlatformClient:
    def __init__(self) -> None:
        self.get_paths: list[str] = []
        self.post_calls: list[tuple[str, dict[str, str]]] = []
        self.delete_paths: list[str] = []

    def get_json(self, path: str) -> dict[str, object]:
        self.get_paths.append(path)
        return {"hats": [], "count": 0, "limit": 100}

    def post_json(self, path: str, payload: dict[str, str]) -> dict[str, object]:
        self.post_calls.append((path, payload))
        return {
            "id": 42,
            "key": "trade-show-sales",
            "handle": "acme/hats/trade-show-sales",
            "display_name": "Trade Show Sales",
            "access": {"mode": "private", "users": [], "count": 0},
            "share_url": "https://tinyhat.ai/hats/opaque",
            "repository_created": True,
        }

    def delete_json(self, path: str) -> dict[str, object]:
        self.delete_paths.append(path)
        return {
            "handle": "acme/hats/trade-show-sales",
            "retired": True,
            "repository_deleted": True,
            "lifecycle_status": "retired",
            "local_checkout_handles": ["acme/hats/trade-show-sales"],
        }


class HatToolTests(unittest.TestCase):
    def test_resume_without_hat_is_a_quiet_noop(self) -> None:
        class NoHatClient(FakePlatformClient):
            def get_json(self, path: str) -> dict[str, object]:
                self.get_paths.append(path)
                raise hats_module.PlatformError("No active Hat installation.", status_code=404)

        client = NoHatClient()
        with mock.patch.object(
            hats_module,
            "build_platform_client",
            return_value=(client, "local_dev"),
        ):
            result = json.loads(hats_module.hats({"action": "resume_installation"}))

        self.assertEqual(result["status"], "none")
        self.assertFalse(result["installation_started"])
        self.assertIsNone(result["onboarding_message"])
        self.assertIn("no user-facing warning", result["agent_instruction"])

    def test_wear_checks_out_read_only_repo_installs_skills_and_starts_transfer(
        self,
    ) -> None:
        class ConsumerClient(FakePlatformClient):
            def post_json(self, path: str, payload: dict[str, str]) -> dict[str, object]:
                self.post_calls.append((path, payload))
                if path.endswith("/wear"):
                    return {
                        "installation_id": "hti_12345678",
                        "hat_handle": "acme/hats/research",
                        "hat_title": "Research",
                        "status": "skills_pending",
                        "source": "existing_agent",
                    }
                return {
                    "installation_id": "hti_12345678",
                    "hat_handle": "acme/hats/research",
                    "hat_title": "Research",
                    "status": "credentials_pending",
                    "source": "existing_agent",
                }

        client = ConsumerClient()
        with (
            mock.patch.object(
                hats_module,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(
                hats_module,
                "run_hat_repository",
                return_value={
                    "action": "checkout",
                    "path": "/tmp/hat-checkout",
                    "head_sha": "a" * 40,
                },
            ) as repository,
            mock.patch.object(
                hats_module,
                "install_hat_skills",
                return_value={"count": 1, "installed_names": ["hat-abc-research"]},
            ) as install,
            mock.patch.object(
                hats_module,
                "start_hat_installation_credentials",
                return_value={"credential_count": 2, "status": "pending"},
            ) as credentials,
        ):
            result = json.loads(
                hats_module.hats({"action": "wear", "identifier": "acme/hats/research"})
            )

        repository.assert_called_once_with(
            {"action": "checkout", "identifier": "acme/hats/research"}
        )
        install.assert_called_once_with("acme/hats/research", "/tmp/hat-checkout")
        credentials.assert_called_once_with(
            installation_id="hti_12345678",
            hat_handle="acme/hats/research",
        )
        self.assertEqual(result["status"], "credentials_pending")
        self.assertTrue(result["installation_started"])
        self.assertEqual(client.post_calls[1][1]["head_sha"], "a" * 40)

    def test_wear_forwards_tinyhat_url_unchanged(self) -> None:
        class ActiveInstallationClient(FakePlatformClient):
            def post_json(self, path: str, payload: dict[str, str]) -> dict[str, object]:
                self.post_calls.append((path, payload))
                return {
                    "installation_id": "hti_12345678",
                    "hat_handle": "acme/hats/research",
                    "hat_title": "Research",
                    "status": "active",
                    "source": "existing_agent",
                }

        client = ActiveInstallationClient()
        hat_url = "https://tinyhat.ai/acme/hats/research"
        with mock.patch.object(
            hats_module,
            "build_platform_client",
            return_value=(client, "local_dev"),
        ):
            result = json.loads(
                hats_module.hats({"action": "wear", "identifier": hat_url})
            )

        self.assertEqual(
            client.post_calls,
            [
                (
                    "/hapi/v1/computers/local-dev/hats/v1/wear",
                    {"identifier": hat_url},
                )
            ],
        )
        self.assertEqual(result["status"], "active")
        self.assertFalse(result["installation_started"])

    def test_repository_checkout_uses_runtime_without_platform_proxy(self) -> None:
        with (
            mock.patch.object(
                hats_module,
                "run_hat_repository",
                return_value={
                    "action": "checkout",
                    "hat_handle": "acme/hats/forecasting",
                    "path": "/home/agent/.hermes/hat-repositories/acme/forecasting",
                    "credential_persisted": False,
                },
            ) as repository,
            mock.patch.object(hats_module, "build_platform_client") as platform,
        ):
            result = json.loads(
                hats_module.hats(
                    {
                        "action": "repository_checkout",
                        "identifier": "forecasting",
                    }
                )
            )

        repository.assert_called_once_with({"action": "checkout", "identifier": "forecasting"})
        platform.assert_not_called()
        self.assertFalse(result["credential_persisted"])
        self.assertIn("clean Git remote", result["agent_instruction"])

    def test_repository_sync_requires_paths_and_commit_message(self) -> None:
        with mock.patch.object(
            hats_module,
            "run_hat_repository",
            return_value={
                "action": "sync",
                "pushed": True,
                "head_sha": "a" * 40,
                "synced_paths": ["HAT.md", "skills/demo/SKILL.md"],
            },
        ) as repository:
            result = json.loads(
                hats_module.hats(
                    {
                        "action": "repository_sync",
                        "identifier": "forecasting",
                        "paths": ["HAT.md", "skills/demo/SKILL.md"],
                        "message": "Add forecasting skill",
                    }
                )
            )

        repository.assert_called_once_with(
            {
                "action": "sync",
                "identifier": "forecasting",
                "paths": ["HAT.md", "skills/demo/SKILL.md"],
                "message": "Add forecasting skill",
            }
        )
        self.assertTrue(result["pushed"])
        self.assertIn("verified head SHA", result["agent_instruction"])

    def test_repository_reset_requires_explicit_confirmation(self) -> None:
        with mock.patch.object(hats_module, "run_hat_repository") as repository:
            result = json.loads(
                hats_module.hats(
                    {
                        "action": "repository_reset",
                        "identifier": "forecasting",
                    }
                )
            )

        repository.assert_not_called()
        self.assertEqual(result["error"], "confirmation_required")

    def test_create_uses_local_computer_endpoint_without_owner_ids(self) -> None:
        client = FakePlatformClient()
        with mock.patch.object(
            hats_module,
            "build_platform_client",
            return_value=(client, "local_dev"),
        ):
            result = json.loads(
                hats_module.hats(
                    {
                        "action": "create",
                        "name": "Trade Show Sales",
                        "access_mode": "private",
                        "allowed_users": ["@buyer"],
                        "default_bot_username": "AdaForecastBot",
                        "default_bot_display_name": "Ada Forecasting Agent",
                    }
                )
            )

        self.assertEqual(
            client.post_calls,
            [
                (
                    "/hapi/v1/computers/local-dev/hats/v1",
                    {
                        "name": "Trade Show Sales",
                        "access_mode": "private",
                        "allowed_users": ["@buyer"],
                        "default_bot_username": "AdaForecastBot",
                        "default_bot_display_name": "Ada Forecasting Agent",
                    },
                )
            ],
        )
        self.assertEqual(result["handle"], "acme/hats/trade-show-sales")
        self.assertNotIn("owner_user_id", client.post_calls[0][1])
        self.assertIn("private", result["agent_instruction"])
        self.assertEqual(result["operation_telemetry"]["action"], "create")
        self.assertIsInstance(result["operation_telemetry"]["elapsed_ms"], int)
        self.assertGreater(
            result["operation_telemetry"]["estimated_tool_output_tokens"],
            0,
        )

    def test_list_and_get_use_gcloud_computer_endpoints(self) -> None:
        client = FakePlatformClient()
        with mock.patch.object(
            hats_module,
            "build_platform_client",
            return_value=(client, "gcloud"),
        ):
            json.loads(hats_module.hats({"action": "list"}))
            json.loads(hats_module.hats({"action": "get", "identifier": "acme/hats/field-sales"}))

        self.assertEqual(
            client.get_paths,
            [
                "/hapi/v1/computers/me/hats/v1",
                "/hapi/v1/computers/me/hats/v1/detail?identifier=acme%2Fhats%2Ffield-sales",
            ],
        )

    def test_create_does_not_require_customer_or_payment(self) -> None:
        client = FakePlatformClient()
        with mock.patch.object(
            hats_module,
            "build_platform_client",
            return_value=(client, "local_dev"),
        ):
            result = json.loads(
                hats_module.hats({"action": "create", "name": "Trade Show Sales"})
            )

        self.assertEqual(client.post_calls[0][1], {"name": "Trade Show Sales"})
        self.assertEqual(result["access"]["mode"], "private")

    def test_update_and_repo_file_use_owner_scoped_platform_routes(self) -> None:
        client = FakePlatformClient()
        with mock.patch.object(
            hats_module,
            "build_platform_client",
            return_value=(client, "local_dev"),
        ):
            hats_module.hats(
                {
                    "action": "update",
                    "identifier": "acme/hats/forecasting",
                    "public_title": "Executive Forecasting",
                }
            )
            hats_module.hats(
                {
                    "action": "put_file",
                    "identifier": "acme/hats/forecasting",
                    "path": "skills/forecasting/SKILL.md",
                    "content": "---\nname: forecasting\n---\n\n# Forecasting\n",
                }
            )

        self.assertEqual(
            client.post_calls[-2:],
            [
                (
                    "/hapi/v1/computers/local-dev/hats/v1/update",
                    {
                        "identifier": "acme/hats/forecasting",
                        "public_title": "Executive Forecasting",
                    },
                ),
                (
                    "/hapi/v1/computers/local-dev/hats/v1/files",
                    {
                        "identifier": "acme/hats/forecasting",
                        "path": "skills/forecasting/SKILL.md",
                        "content": "---\nname: forecasting\n---\n\n# Forecasting\n",
                    },
                ),
            ],
        )

    def test_update_rejects_allowed_users_replace(self) -> None:
        client = FakePlatformClient()
        with mock.patch.object(
            hats_module,
            "build_platform_client",
            return_value=(client, "local_dev"),
        ):
            result = json.loads(
                hats_module.hats(
                    {
                        "action": "update",
                        "identifier": "acme/hats/forecasting",
                        "allowed_users": ["@buyer"],
                    }
                )
            )

        self.assertEqual(result["error"], "invalid_parameter_for_action")
        self.assertIn("add_user", result["message"])
        self.assertEqual(client.post_calls, [])

    def test_update_can_change_audience_and_handle_without_recreating_hat(
        self,
    ) -> None:
        client = FakePlatformClient()

        def fake_get(path: str) -> dict[str, object]:
            client.get_paths.append(path)
            return {
                "id": 42,
                "handle": "acme/hats/forecasting",
            }

        def fake_post(path: str, payload: dict[str, str]) -> dict[str, object]:
            client.post_calls.append((path, payload))
            return {
                "id": 42,
                "key": "executive-forecasting",
                "handle": "acme/hats/executive-forecasting",
                "display_name": "Trade Show Sales",
                "access": {"mode": "private", "users": [], "count": 0},
                "share_url": "https://tinyhat.ai/acme/hats/executive-forecasting",
                "repository_created": True,
            }

        client.get_json = fake_get  # type: ignore[method-assign]
        client.post_json = fake_post  # type: ignore[method-assign]
        with (
            mock.patch.object(
                hats_module,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(
                hats_module,
                "rename_hat_secret_store",
                return_value={"renamed": True, "already_current": False},
            ) as rename_store,
        ):
            result = json.loads(
                hats_module.hats(
                    {
                        "action": "update",
                        "identifier": "acme/hats/forecasting",
                        "add_user": "@newbuyer",
                        "new_key": "executive-forecasting",
                    }
                )
            )

        self.assertEqual(
            client.post_calls,
            [
                (
                    "/hapi/v1/computers/local-dev/hats/v1/update",
                    {
                        "identifier": "acme/hats/forecasting",
                        "add_user": "@newbuyer",
                        "new_key": "executive-forecasting",
                    },
                )
            ],
        )
        rename_store.assert_called_once_with(
            "acme/hats/forecasting",
            "acme/hats/executive-forecasting",
        )
        self.assertEqual(result["id"], 42)
        self.assertEqual(result["handle"], "acme/hats/executive-forecasting")
        self.assertTrue(result["local_store_renamed"])

    def test_update_can_replace_managed_bot_defaults(self) -> None:
        client = FakePlatformClient()
        with mock.patch.object(
            hats_module,
            "build_platform_client",
            return_value=(client, "local_dev"),
        ):
            hats_module.hats(
                {
                    "action": "update",
                    "identifier": "acme/hats/forecasting",
                    "default_bot_username": "@UpdatedForecastBot",
                    "default_bot_display_name": "Updated Forecaster",
                }
            )

        self.assertEqual(
            client.post_calls[-1],
            (
                "/hapi/v1/computers/local-dev/hats/v1/update",
                {
                    "identifier": "acme/hats/forecasting",
                    "default_bot_username": "@UpdatedForecastBot",
                    "default_bot_display_name": "Updated Forecaster",
                },
            ),
        )

    def test_update_without_mutable_fields_is_self_correcting(self) -> None:
        result = json.loads(
            hats_module.hats(
                {
                    "action": "update",
                    "identifier": "acme/hats/forecasting",
                }
            )
        )

        self.assertEqual(result["error"], "missing_required_parameter")
        self.assertEqual(
            result["missing"],
            ["a Hat metadata field"],
        )

    def test_list_credentials_uses_computer_local_saved_state(self) -> None:
        client = FakePlatformClient()

        def fake_get(path: str) -> dict[str, object]:
            client.get_paths.append(path)
            return {
                "handle": "acme/hats/forecasting",
                "credentials": [
                    {"name": "EXA_API_KEY", "saved_at": None},
                    {"name": "GITHUB_TOKEN", "saved_at": "stale-platform-value"},
                ],
            }

        client.get_json = fake_get  # type: ignore[method-assign]
        with (
            mock.patch.object(
                hats_module,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(
                hats_module,
                "list_hat_secret_names",
                return_value={
                    "handle": "acme/hats/forecasting",
                    "names": ["EXA_API_KEY"],
                    "count": 1,
                    "value_available": False,
                },
            ),
        ):
            result = json.loads(
                hats_module.hats(
                    {
                        "action": "list_credentials",
                        "identifier": "acme/hats/forecasting",
                    }
                )
            )

        self.assertEqual(result["local_value_status"], "available")
        self.assertTrue(result["credentials"][0]["has_local_value"])
        self.assertFalse(result["credentials"][1]["has_local_value"])
        self.assertNotIn("value", result["credentials"][0])

    def test_list_credentials_removes_stale_state_when_local_check_fails(self) -> None:
        client = FakePlatformClient()

        def fake_get(_path: str) -> dict[str, object]:
            return {
                "handle": "acme/hats/forecasting",
                "credentials": [
                    {"name": "EXA_API_KEY", "has_local_value": False},
                ],
            }

        client.get_json = fake_get  # type: ignore[method-assign]
        with (
            mock.patch.object(
                hats_module,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(
                hats_module,
                "list_hat_secret_names",
                side_effect=hats_module.HatSecretStoreError("store unavailable"),
            ),
        ):
            result = json.loads(
                hats_module.hats(
                    {
                        "action": "list_credentials",
                        "identifier": "acme/hats/forecasting",
                    }
                )
            )

        self.assertEqual(result["local_value_status"], "unavailable")
        self.assertNotIn("has_local_value", result["credentials"][0])

    def test_remove_credential_deletes_local_value_before_metadata(self) -> None:
        client = FakePlatformClient()

        def fake_get(path: str) -> dict[str, object]:
            client.get_paths.append(path)
            return {"handle": "acme/hats/forecasting"}

        client.get_json = fake_get  # type: ignore[method-assign]
        with (
            mock.patch.object(
                hats_module,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(
                hats_module,
                "remove_hat_secret",
                return_value={"removed": True},
            ) as remove_local,
        ):
            result = json.loads(
                hats_module.hats(
                    {
                        "action": "remove_credential",
                        "identifier": "forecasting",
                        "credential_name": "EXA_API_KEY",
                        "confirmed": True,
                    }
                )
            )

        remove_local.assert_called_once_with(
            "acme/hats/forecasting",
            "EXA_API_KEY",
        )
        self.assertEqual(
            client.post_calls[-1],
            (
                "/hapi/v1/computers/local-dev/hats/v1/credentials/remove",
                {
                    "identifier": "acme/hats/forecasting",
                    "name": "EXA_API_KEY",
                },
            ),
        )
        self.assertTrue(result["local_value_removed"])

    def test_delete_requires_confirmation_then_retires_hat_and_removes_local_store(
        self,
    ) -> None:
        client = FakePlatformClient()

        def fake_get(path: str) -> dict[str, object]:
            client.get_paths.append(path)
            return {"handle": "acme/hats/forecasting"}

        def fake_delete(path: str) -> dict[str, object]:
            client.delete_paths.append(path)
            return {
                "handle": "acme/hats/forecasting",
                "retired": True,
                "repository_deleted": True,
                "lifecycle_status": "retired",
                "local_checkout_handles": [
                    "acme/hats/forecasting",
                    "acme/hats/forecasting-before-rename",
                ],
                "local_checkouts": [
                    {
                        "handle": "acme/hats/forecasting",
                        "repository_owner": "tinyhat-ai",
                        "repository_name": "acme--hats--forecasting",
                        "repository_url": "https://github.com/tinyhat-ai/acme--hats--forecasting.git",
                    },
                    {
                        "handle": "acme/hats/forecasting-before-rename",
                        "repository_owner": "tinyhat-ai",
                        "repository_name": "acme--hats--forecasting-before-rename",
                        "repository_url": "https://github.com/tinyhat-ai/acme--hats--forecasting-before-rename.git",
                    },
                ],
            }

        client.get_json = fake_get  # type: ignore[method-assign]
        client.delete_json = fake_delete  # type: ignore[method-assign]
        with (
            mock.patch.object(
                hats_module,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(
                hats_module,
                "delete_hat_secret_store",
                return_value={"removed": True},
            ) as delete_local,
            mock.patch.object(
                hats_module,
                "run_hat_repository",
                return_value={
                    "schema": "tinyhat_hat_repository_v1",
                    "action": "delete_local",
                    "hat_handle": "acme/hats/forecasting",
                    "path": "/home/agent/.hermes/hat-repositories/acme/forecasting",
                    "removed": True,
                },
            ) as delete_checkout,
        ):
            refused = json.loads(
                hats_module.hats(
                    {
                        "action": "delete",
                        "identifier": "acme/hats/forecasting",
                    }
                )
            )
            deleted = json.loads(
                hats_module.hats(
                    {
                        "action": "delete",
                        "identifier": "acme/hats/forecasting",
                        "confirmed": True,
                    }
                )
            )

        self.assertEqual(refused["error"], "confirmation_required")
        self.assertIn("retire this exact Hat", refused["message"])
        self.assertIn(
            "requires GitHub to acknowledge deleting its private repository",
            refused["message"],
        )
        self.assertIn("already-installed consumer agents", refused["message"])
        self.assertNotRegex(refused["message"].lower(), r"\bpermanent(?:ly)?\b")
        self.assertEqual(
            client.get_paths,
            [],
        )
        self.assertEqual(
            client.delete_paths,
            ["/hapi/v1/computers/local-dev/hats/v1/retire?identifier=acme%2Fhats%2Fforecasting"],
        )
        self.assertEqual(
            delete_local.call_args_list,
            [
                mock.call("acme/hats/forecasting"),
                mock.call("acme/hats/forecasting-before-rename"),
            ],
        )
        self.assertEqual(
            delete_checkout.call_args_list,
            [
                mock.call(
                    {
                        "action": "delete_local",
                        "identifier": "acme/hats/forecasting",
                        "repository": {
                            "owner": "tinyhat-ai",
                            "name": "acme--hats--forecasting",
                            "url": "https://github.com/tinyhat-ai/acme--hats--forecasting.git",
                        },
                    }
                ),
                mock.call(
                    {
                        "action": "delete_local",
                        "identifier": "acme/hats/forecasting-before-rename",
                        "repository": {
                            "owner": "tinyhat-ai",
                            "name": "acme--hats--forecasting-before-rename",
                            "url": "https://github.com/tinyhat-ai/acme--hats--forecasting-before-rename.git",
                        },
                    }
                ),
            ],
        )
        self.assertTrue(deleted["retired"])
        self.assertEqual(deleted["lifecycle_status"], "retired")
        self.assertTrue(deleted["local_store_removed"])
        self.assertTrue(deleted["local_checkout_cleanup_complete"])
        self.assertIn("Hat was retired", deleted["agent_instruction"])
        self.assertIn(
            "GitHub acknowledged deletion of its private repository",
            deleted["agent_instruction"],
        )
        self.assertIn(
            "from the Hat's GitHub organization",
            deleted["agent_instruction"],
        )
        self.assertIn("already-installed consumer agents", deleted["agent_instruction"])
        self.assertNotRegex(
            deleted["agent_instruction"].lower(),
            r"\bpermanent(?:ly)?\b",
        )

    def test_delete_does_not_claim_retirement_without_lifecycle_receipt(self) -> None:
        client = FakePlatformClient()

        def fake_delete(path: str) -> dict[str, object]:
            client.delete_paths.append(path)
            return {
                "handle": "acme/hats/forecasting",
                "retired": True,
                "repository_deleted": True,
                "local_checkout_handles": ["acme/hats/forecasting"],
            }

        client.delete_json = fake_delete  # type: ignore[method-assign]
        with (
            mock.patch.object(
                hats_module,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(hats_module, "delete_hat_secret_store") as delete_local,
            mock.patch.object(hats_module, "run_hat_repository") as delete_checkout,
        ):
            result = json.loads(
                hats_module.hats(
                    {
                        "action": "delete",
                        "identifier": "acme/hats/forecasting",
                        "confirmed": True,
                    }
                )
            )

        self.assertNotIn("was retired", result["agent_instruction"])
        self.assertNotIn("already-installed consumer agents", result["agent_instruction"])
        self.assertIn("did not contain a verifiable", result["agent_instruction"])
        self.assertFalse(result["local_checkout_cleanup_complete"])
        self.assertFalse(result["local_store_removed"])
        delete_local.assert_not_called()
        delete_checkout.assert_not_called()

    def test_delete_404_fails_closed_without_local_cleanup(self) -> None:
        client = FakePlatformClient()

        def fake_delete(path: str) -> dict[str, object]:
            client.delete_paths.append(path)
            raise hats_module.PlatformError(
                "Platform request failed with HTTP 404: Not Found",
                status_code=404,
            )

        client.delete_json = fake_delete  # type: ignore[method-assign]
        with (
            mock.patch.object(
                hats_module,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(hats_module, "delete_hat_secret_store") as delete_local,
            mock.patch.object(hats_module, "run_hat_repository") as delete_checkout,
        ):
            result = json.loads(
                hats_module.hats(
                    {
                        "action": "delete",
                        "identifier": "acme/hats/forecasting",
                        "confirmed": True,
                    }
                )
            )

        self.assertEqual(result["error"], "platform_request_failed")
        self.assertIn("HTTP 404", result["message"])
        self.assertEqual(
            client.delete_paths,
            ["/hapi/v1/computers/local-dev/hats/v1/retire?identifier=acme%2Fhats%2Fforecasting"],
        )
        delete_local.assert_not_called()
        delete_checkout.assert_not_called()

    def test_retired_receipt_does_not_invent_repository_deletion(self) -> None:
        client = FakePlatformClient()

        def fake_delete(path: str) -> dict[str, object]:
            client.delete_paths.append(path)
            return {
                "handle": "acme/hats/forecasting",
                "retired": True,
                "repository_deleted": False,
                "lifecycle_status": "retired",
                "local_checkout_handles": [],
                "local_checkouts": [],
            }

        client.delete_json = fake_delete  # type: ignore[method-assign]
        with (
            mock.patch.object(
                hats_module,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(
                hats_module,
                "delete_hat_secret_store",
                return_value={"removed": False},
            ),
        ):
            result = json.loads(
                hats_module.hats(
                    {
                        "action": "delete",
                        "identifier": "acme/hats/forecasting",
                        "confirmed": True,
                    }
                )
            )

        self.assertIn("did not contain a verifiable", result["agent_instruction"])
        self.assertNotRegex(
            result["agent_instruction"].lower(),
            r"\bpermanent(?:ly)?\b",
        )
        self.assertFalse(result["local_store_removed"])
        self.assertFalse(result["local_checkout_cleanup_complete"])

    def test_delete_reports_retiring_receipt_as_retryable(self) -> None:
        client = FakePlatformClient()

        def fake_delete(path: str) -> dict[str, object]:
            client.delete_paths.append(path)
            return {
                "handle": "acme/hats/forecasting",
                "retired": False,
                "repository_deleted": False,
                "lifecycle_status": "retiring",
                "local_checkout_handles": ["acme/hats/forecasting"],
            }

        client.delete_json = fake_delete  # type: ignore[method-assign]
        with (
            mock.patch.object(
                hats_module,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(hats_module, "delete_hat_secret_store") as delete_local,
            mock.patch.object(hats_module, "run_hat_repository") as delete_checkout,
        ):
            result = json.loads(
                hats_module.hats(
                    {
                        "action": "delete",
                        "identifier": "acme/hats/forecasting",
                        "confirmed": True,
                    }
                )
            )

        self.assertIn("still pending", result["agent_instruction"])
        self.assertNotIn("already-installed consumer agents", result["agent_instruction"])
        self.assertFalse(result["local_checkout_cleanup_complete"])
        self.assertFalse(result["local_store_removed"])
        delete_local.assert_not_called()
        delete_checkout.assert_not_called()

    def test_define_then_configure_uses_one_hat_bundle_flow(self) -> None:
        client = FakePlatformClient()
        with (
            mock.patch.object(
                hats_module,
                "build_platform_client",
                return_value=(client, "local_dev"),
            ),
            mock.patch.object(
                hats_module,
                "start_hat_credentials_handoff",
                return_value="One encrypted form sent.",
            ) as start_bundle,
        ):
            defined = json.loads(
                hats_module.hats(
                    {
                        "action": "define_credential",
                        "identifier": "acme/hats/forecasting",
                        "credential_name": "EXA_API_KEY",
                        "description": "Research provider access",
                    }
                )
            )
            configured = hats_module.hats(
                {
                    "action": "configure_credentials",
                    "identifier": "acme/hats/forecasting",
                }
            )

        self.assertEqual(
            client.post_calls[-1],
            (
                "/hapi/v1/computers/local-dev/hats/v1/credentials/define",
                {
                    "identifier": "acme/hats/forecasting",
                    "name": "EXA_API_KEY",
                    "description": "Research provider access",
                },
            ),
        )
        self.assertIn("configure_credentials", defined["agent_instruction"])
        start_bundle.assert_called_once_with("acme/hats/forecasting")
        self.assertEqual(configured, "One encrypted form sent.")


if __name__ == "__main__":
    unittest.main()
