"""Tests for the Tinyhat shareable-hats plugin tool."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))

from tinyhat import hats as hats_module  # noqa: E402


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
            "customer_email": "buyer@example.com",
            "share_url": "https://tinyhat.ai/hats/opaque",
            "repository_created": True,
        }

    def delete_json(self, path: str) -> dict[str, object]:
        self.delete_paths.append(path)
        return {
            "handle": "acme/hats/trade-show-sales",
            "deleted": True,
            "repository_deleted": True,
        }


class HatToolTests(unittest.TestCase):
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
                        "customer_email": "buyer@example.com",
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
                        "customer_email": "buyer@example.com",
                        "default_bot_username": "AdaForecastBot",
                        "default_bot_display_name": "Ada Forecasting Agent",
                    },
                )
            ],
        )
        self.assertEqual(result["handle"], "acme/hats/trade-show-sales")
        self.assertNotIn("owner_user_id", client.post_calls[0][1])
        self.assertIn("wears this hat", result["agent_instruction"])

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

    def test_create_missing_customer_email_is_self_correcting(self) -> None:
        result = json.loads(hats_module.hats({"action": "create", "name": "Trade Show Sales"}))

        self.assertEqual(result["schema"], "tinyhat_tool_error_v1")
        self.assertEqual(result["error"], "missing_required_parameter")
        self.assertEqual(result["missing"], ["customer_email"])

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

    def test_update_can_change_customer_and_handle_without_recreating_hat(
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
                "customer_email": "new-buyer@example.com",
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
                        "customer_email": "new-buyer@example.com",
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
                        "customer_email": "new-buyer@example.com",
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
            ["public_title, customer_email, or new_key"],
        )

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

    def test_delete_requires_confirmation_then_removes_platform_and_local_store(
        self,
    ) -> None:
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
                "delete_hat_secret_store",
                return_value={"removed": True},
            ) as delete_local,
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
        self.assertEqual(
            client.get_paths,
            ["/hapi/v1/computers/local-dev/hats/v1/detail?identifier=acme%2Fhats%2Fforecasting"],
        )
        self.assertEqual(
            client.delete_paths,
            ["/hapi/v1/computers/local-dev/hats/v1?identifier=acme%2Fhats%2Fforecasting"],
        )
        delete_local.assert_called_once_with("acme/hats/forecasting")
        self.assertTrue(deleted["deleted"])
        self.assertTrue(deleted["local_store_removed"])

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
