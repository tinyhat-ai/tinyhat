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
                    },
                )
            ],
        )
        self.assertEqual(result["handle"], "acme/hats/trade-show-sales")
        self.assertNotIn("owner_user_id", client.post_calls[0][1])
        self.assertIn("under construction", result["agent_instruction"])

    def test_list_and_get_use_gcloud_computer_endpoints(self) -> None:
        client = FakePlatformClient()
        with mock.patch.object(
            hats_module,
            "build_platform_client",
            return_value=(client, "gcloud"),
        ):
            json.loads(hats_module.hats({"action": "list"}))
            json.loads(
                hats_module.hats(
                    {"action": "get", "identifier": "acme/hats/field-sales"}
                )
            )

        self.assertEqual(
            client.get_paths,
            [
                "/hapi/v1/computers/me/hats/v1",
                "/hapi/v1/computers/me/hats/v1/detail?identifier=acme%2Fhats%2Ffield-sales",
            ],
        )

    def test_create_missing_customer_email_is_self_correcting(self) -> None:
        result = json.loads(
            hats_module.hats({"action": "create", "name": "Trade Show Sales"})
        )

        self.assertEqual(result["schema"], "tinyhat_tool_error_v1")
        self.assertEqual(result["error"], "missing_required_parameter")
        self.assertEqual(result["missing"], ["customer_email"])


if __name__ == "__main__":
    unittest.main()
