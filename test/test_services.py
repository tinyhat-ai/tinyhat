"""Usage: python -m unittest discover -s test -p test_services.py"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))
from package_support import load_local_tinyhat

load_local_tinyhat(REPO_ROOT)

import tinyhat
from test_hermes_adapter import FakeHermesContext
from tinyhat import schemas
from tinyhat.capabilities.services import tool


class ServicesTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.base_url = "https://api.tinyhat.ai"
        self.client.get_json.return_value = {"data": []}
        self.client.post_json.return_value = {"status": "not_created"}
        self.patch = patch.object(tool, "build_platform_client", return_value=(self.client, "gcloud"))
        self.builder = self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_tool_and_skill_are_registered(self):
        context = FakeHermesContext()
        tinyhat.register(context)
        self.assertIn("tinyhat-services", context.skills)
        self.assertIs(context.tools["tinyhat_services"]["handler"], tool.services)
        self.assertIs(context.tools["tinyhat_services"]["schema"], schemas.TINYHAT_SERVICES_SCHEMA)

    def test_catalog_and_reviewed_write_use_only_computer_identity(self):
        result = json.loads(tool.services({"action": "catalog_services", "provider_name": "Future Provider"}))
        self.assertEqual(result, {"data": []})
        self.client.get_json.assert_called_once_with(
            tool.BASE + "/catalog/services?provider_name=Future%20Provider"
        )
        intent_id = "a" * 36
        self.client.post_json.return_value = {
            "id": intent_id,
            "review_url": "https://computer.tinyhat.ai/tinyhat/computers/computer_4/services/review/" + intent_id,
            "status": "awaiting_approval",
        }
        request = {"action": "create_resource", "provider": "prvdr_future", "service_ref": "svc_future", "name": "Sample"}
        result = json.loads(tool.services({"action": "prepare", "request": request}))
        self.assertEqual(result["status"], "awaiting_approval")
        self.client.post_json.assert_called_once_with(tool.BASE + "/intents", request)
        result = json.loads(tool.services({"action": "create_project"}))
        self.assertEqual(result["status"], "awaiting_approval")
        self.client.post_json.assert_called_with(tool.BASE + "/project", {})
        self.assertNotIn("approve", schemas.TINYHAT_SERVICES_SCHEMA["properties"]["action"]["enum"])

    def test_rejects_foreign_identity_and_unsafe_inputs(self):
        self.assertEqual(json.loads(tool.services({"action": "status", "account_id": "other"}))["error"], "invalid_arguments")
        self.assertEqual(json.loads(tool.services({"action": "prepare", "request": {"action": "buy_domain", "stripe_account": "other"}}))["error"], "invalid_arguments")
        self.builder.assert_not_called()
        self.client.post_json.return_value = {
            "id": "a" * 36,
            "review_url": "https://evil.example/tinyhat/computers/computer_4/services/review/" + "a" * 36,
        }
        result = json.loads(tool.services({"action": "prepare", "request": {"action": "remove_resource", "resource_id": "resource_12345"}}))
        self.assertEqual(result["error"], "invalid_platform_response")


if __name__ == "__main__":
    unittest.main()
