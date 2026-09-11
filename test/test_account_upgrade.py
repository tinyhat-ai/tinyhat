"""Usage: python -m unittest discover -s test -p test_account_upgrade.py"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))
from package_support import load_local_tinyhat

load_local_tinyhat(REPO_ROOT)

from tinyhat import context, schemas
from tinyhat.capabilities.account_upgrade import tool
from tinyhat.platform import PlatformError
from test_hermes_adapter import FakeHermesContext
import tinyhat


class AccountUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.get_json.return_value = {
            "status": "not_started",
            "available": True,
            "terms_version": "2026-09-11",
        }
        self.client.post_json.return_value = {"status": "pending", "spending_limit_cents": 0}
        self.patch = patch.object(
            tool, "build_platform_client", return_value=(self.client, "gcloud")
        )
        self.builder = self.patch.start()
        self.addCleanup(self.patch.stop)

    def payload(self):
        return {
            "action": "submit",
            "individual": {"given_name": "Synthetic"},
            "consent": {
                "terms_version": "2026-09-11",
                **{key: True for key in tool.APPROVALS},
            },
        }

    def test_registration_and_existing_customer_discovery(self):
        ctx = FakeHermesContext()
        tinyhat.register(ctx)
        self.assertIn("tinyhat-account-upgrade", ctx.skills)
        self.assertIs(ctx.tools["tinyhat_account_upgrade"]["handler"], tool.account_upgrade)
        self.assertIs(
            ctx.tools["tinyhat_account_upgrade"]["schema"], schemas.TINYHAT_ACCOUNT_UPGRADE_SCHEMA
        )
        self.assertTrue(context.should_inject_tinyhat_context("Enable Stripe Projects for me"))

    def test_routes_use_machine_identity_and_forward_only_authorized_payload(self):
        self.assertEqual(
            json.loads(tool.account_upgrade({"action": "status"}))["status"], "not_started"
        )
        self.client.get_json.assert_called_once_with(f"{tool.BASE}/upgrade")
        payload = self.payload()
        self.assertEqual(json.loads(tool.account_upgrade(payload))["status"], "pending")
        self.client.post_json.assert_called_once_with(
            f"{tool.BASE}/upgrade",
            {
                "individual": payload["individual"],
                "consent": payload["consent"],
            },
        )
        self.builder.assert_called_with(timeout_seconds=45)

    def test_unapproved_or_coerced_consent_makes_no_network_request(self):
        for key in tool.APPROVALS:
            for invalid in (False, 1, "true", None):
                with self.subTest(key=key, invalid=invalid):
                    payload = self.payload()
                    payload["consent"][key] = invalid
                    result = json.loads(tool.account_upgrade(payload))
                    self.assertEqual(result["error"], "human_approval_required")
        self.builder.assert_not_called()

    def test_targeting_another_owner_is_rejected_before_network(self):
        for key in ("account_id", "user_id", "computer_id", "payment_method"):
            payload = {**self.payload(), key: "other"}
            self.assertEqual(
                json.loads(tool.account_upgrade(payload))["error"], "invalid_arguments"
            )
        self.builder.assert_not_called()

    def test_only_safe_status_fields_return(self):
        self.client.get_json.return_value = {
            "status": "ready",
            "private_card": "do-not-return",
            "individual": {"date_of_birth": "private"},
        }
        result = tool.account_upgrade({"action": "status"})
        self.assertEqual(json.loads(result), {"status": "ready"})

    def test_raw_provider_errors_never_echo_details_or_tokens(self):
        self.client.post_json.side_effect = PlatformError(
            "private-personal-data-and-token", status_code=503
        )
        result = tool.account_upgrade(self.payload())
        self.assertNotIn("private-personal-data", result)
        self.assertEqual(json.loads(result)["error"], "upgrade_submission_uncertain")

    def test_missing_owner_email_preserves_existing_account(self):
        self.client.get_json.side_effect = PlatformError(
            "private", status_code=409, response={"error": {"code": "owner_email_required"}}
        )
        result = json.loads(tool.account_upgrade({"action": "status"}))
        self.assertEqual(result["error"], "owner_email_required")
        self.assertIn("existing Tinyhat profile", result["message"])
        self.assertNotIn("private", result["message"])

    def test_verification_link_rejects_untrusted_hosts(self):
        self.client.post_json.return_value = {
            "url": "https://connect.stripe.com.evil.example/verify"
        }
        result = tool.account_upgrade({"action": "verification_link"})
        self.assertEqual(json.loads(result)["error"], "invalid_platform_response")
        self.client.post_json.return_value = {"url": "https://connect.stripe.com/setup/s/fixture"}
        self.assertIn("url", json.loads(tool.account_upgrade({"action": "verification_link"})))

    def test_local_token_does_not_masquerade_as_cloud_identity(self):
        self.builder.return_value = (self.client, "local_dev")
        self.assertEqual(
            json.loads(tool.account_upgrade({"action": "status"}))["error"],
            "computer_identity_required",
        )
        self.client.get_json.assert_not_called()
