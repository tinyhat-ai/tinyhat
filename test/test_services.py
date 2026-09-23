"""Usage: python -m unittest discover -s test -p test_services.py"""

import base64
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))
from package_support import load_local_tinyhat  # noqa: E402

load_local_tinyhat(REPO_ROOT)

import tinyhat  # noqa: E402
from test_hermes_adapter import FakeHermesContext  # noqa: E402
from tinyhat import schemas  # noqa: E402
from tinyhat.capabilities.services import (  # noqa: E402
    environment,
    tool,
)
from tinyhat.platform import PlatformError  # noqa: E402


class ServicesTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.base_url = "https://api.tinyhat.ai"
        self.client.get_json.return_value = {"data": []}
        self.client.post_json.return_value = {"status": "not_created"}
        self.patch = patch.object(
            tool, "build_platform_client", return_value=(self.client, "gcloud")
        )
        self.builder = self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_tool_and_skill_are_registered(self):
        context = FakeHermesContext()
        tinyhat.register(context)
        self.assertIn("tinyhat-services", context.skills)
        self.assertIs(context.tools["tinyhat_services"]["handler"], tool.services)
        self.assertIs(context.tools["tinyhat_services"]["schema"], schemas.TINYHAT_SERVICES_SCHEMA)

    def test_catalog_and_reviewed_write_use_only_computer_identity(self):
        result = json.loads(
            tool.services({"action": "catalog_services", "provider_name": "Future Provider"})
        )
        self.assertEqual(result, {"data": []})
        self.client.get_json.assert_called_once_with(
            tool.BASE + "/catalog/services?provider_name=Future%20Provider"
        )
        intent_id = "a" * 36
        self.client.post_json.return_value = {
            "id": intent_id,
            "review_url": "https://computer.tinyhat.ai/tinyhat/computers/computer_4/services/review/"
            + intent_id,
            "status": "awaiting_approval",
        }
        request = {
            "action": "create_resource",
            "provider": "prvdr_future",
            "service_ref": "svc_future",
            "name": "Sample",
        }
        result = json.loads(tool.services({"action": "prepare", "request": request}))
        self.assertEqual(result["status"], "awaiting_approval")
        self.client.post_json.assert_called_once_with(tool.BASE + "/intents", request)
        result = json.loads(tool.services({"action": "create_project"}))
        self.assertEqual(result["status"], "awaiting_approval")
        self.client.post_json.assert_called_with(tool.BASE + "/project", {})
        self.assertNotIn("approve", schemas.TINYHAT_SERVICES_SCHEMA["properties"]["action"]["enum"])

    def test_account_resource_association_still_requires_owner_review(self):
        allowed = schemas.TINYHAT_SERVICES_SCHEMA["properties"]["request"]["properties"]["action"][
            "enum"
        ]
        self.assertIn("attach_resource", allowed)
        self.assertIn("detach_resource", allowed)
        self.client.post_json.return_value = {
            "id": "a" * 36,
            "review_url": "https://computer.tinyhat.ai/tinyhat/computers/computer_4/services/review/"
            + "a" * 36,
            "status": "awaiting_approval",
        }
        request = {"action": "attach_resource", "resource_id": "resource_123456789"}
        result = json.loads(tool.services({"action": "prepare", "request": request}))
        self.assertEqual(result["status"], "awaiting_approval")
        self.client.post_json.assert_called_once_with(tool.BASE + "/intents", request)

    def test_rejects_foreign_identity_and_unsafe_inputs(self):
        self.assertEqual(
            json.loads(tool.services({"action": "status", "account_id": "other"}))["error"],
            "invalid_arguments",
        )
        self.assertEqual(
            json.loads(
                tool.services(
                    {
                        "action": "prepare",
                        "request": {"action": "buy_domain", "stripe_account": "other"},
                    }
                )
            )["error"],
            "invalid_arguments",
        )
        self.builder.assert_not_called()
        self.client.post_json.return_value = {
            "id": "a" * 36,
            "review_url": "https://evil.example/tinyhat/computers/computer_4/services/review/"
            + "a" * 36,
        }
        result = json.loads(
            tool.services(
                {
                    "action": "prepare",
                    "request": {"action": "remove_resource", "resource_id": "resource_12345"},
                }
            )
        )
        self.assertEqual(result["error"], "invalid_platform_response")

    def test_development_review_origin_is_operator_configured(self):
        url = (
            "https://dev-computer.example.test/tinyhat/computers/computer_4/services/review/"
            + "a" * 36
        )
        with patch(
            "tinyhat.capabilities.account_upgrade.tool.runtime_env",
            return_value={"TINYHAT_ACCOUNT_REVIEW_ORIGIN": "https://dev-computer.example.test"},
        ):
            self.assertTrue(tool._review_url(url, self.client.base_url))
            self.assertFalse(
                tool._review_url(
                    url.replace("dev-computer.example.test", "evil.example"), self.client.base_url
                )
            )
            self.assertFalse(
                tool._review_url(
                    url.replace("dev-computer.example.test", "dev-computer.example.test:8443"),
                    self.client.base_url,
                )
            )
            self.assertTrue(
                tool._review_url(
                    url.replace("https://dev-computer.example.test", "http://127.0.0.1:8040"),
                    "http://127.0.0.1:8040",
                )
            )

    def test_review_button_and_non_telegram_fallback(self):
        url = "https://computer.tinyhat.ai/tinyhat/computers/computer_4/services/review/" + "a" * 36
        with (
            patch("tinyhat.tools._telegram_credentials", return_value=("test-token", 123)),
            patch("tinyhat.tools._telegram_send_message", return_value={"ok": True}) as send,
        ):
            self.assertTrue(tool._send_service_review_button(url))
            self.assertEqual(
                send.call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["url"], url
            )
            self.assertTrue(
                tool._send_service_review_button(
                    url,
                    {"action": "submit_account_information", "provider_name": "Example Provider"},
                )
            )
            self.assertIn("Example Provider needs", send.call_args.kwargs["text"])
        with patch("tinyhat.tools._telegram_credentials", side_effect=RuntimeError("unavailable")):
            self.assertFalse(tool._send_service_review_button(url))

    def test_page_round_trip_and_computer_identity(self):
        page_url = "/v2/provisioning/resources?project=project_123&page=abc"
        self.assertEqual(
            json.loads(tool.services({"action": "resources", "page_url": page_url})), {"data": []}
        )
        self.client.get_json.assert_called_once_with(
            tool.BASE
            + "/resources?page_url=%2Fv2%2Fprovisioning%2Fresources%3Fproject%3Dproject_123%26page%3Dabc"
        )
        self.client.get_json.reset_mock()
        self.assertEqual(
            json.loads(
                tool.services({"action": "connection_request", "request_id": "facctrq_123456789"})
            ),
            {"data": []},
        )
        self.client.get_json.assert_called_once_with(
            tool.BASE + "/provider-connection-requests/facctrq_123456789"
        )
        self.builder.return_value = (self.client, "local_dev")
        refused = json.loads(tool.services({"action": "status"}))
        self.assertEqual(refused["error"], "computer_identity_required")

    def test_definite_refusal_preserves_actionable_message(self):
        self.client.post_json.side_effect = PlatformError(
            "request refused",
            status_code=409,
            response={
                "error": {
                    "code": "provider_allowance_required",
                    "message": "Reserve an allowance first.",
                }
            },
        )
        result = json.loads(
            tool.services(
                {
                    "action": "prepare",
                    "request": {
                        "action": "reserve_provider_allowance",
                        "provider": "prvdr_example",
                        "limit_cents": 500,
                    },
                }
            )
        )
        self.assertEqual(result["error"], "provider_allowance_required")
        self.assertEqual(result["message"], "Reserve an allowance first.")

    def test_timeout_is_uncertain_for_prepare_and_execute(self):
        self.client.post_json.side_effect = PlatformError("timed out")
        result = json.loads(tool.services({"action": "execute", "intent_id": "a" * 36}))
        self.assertEqual(result["error"], "service_request_uncertain")
        self.assertIn("Check its status", result["message"])
        result = json.loads(
            tool.services(
                {
                    "action": "prepare",
                    "request": {"action": "create_resource", "provider": "prvdr_future"},
                }
            )
        )
        self.assertEqual(result["error"], "service_request_uncertain")
        self.assertIn("do not prepare this action again", result["message"])
        self.client.post_json.side_effect = TimeoutError("response timed out")
        result = json.loads(
            tool.services(
                {
                    "action": "prepare",
                    "request": {"action": "create_resource", "provider": "prvdr_future"},
                }
            )
        )
        self.assertEqual(result["error"], "service_request_uncertain")
        self.assertIn("do not prepare this action again", result["message"])
        result = json.loads(tool.services({"action": "execute", "intent_id": "a" * 36}))
        self.assertEqual(result["error"], "service_request_uncertain")
        self.client.post_json.side_effect = PlatformError(
            "gateway failed",
            status_code=500,
            response={"error": {"code": "internal_error", "message": "Retry shortly."}},
        )
        result = json.loads(
            tool.services(
                {
                    "action": "prepare",
                    "request": {"action": "create_resource", "provider": "prvdr_future"},
                }
            )
        )
        self.assertEqual(result["error"], "service_request_uncertain")
        self.client.post_json.side_effect = None
        self.client.get_json.side_effect = PlatformError("timed out")
        result = json.loads(tool.services({"action": "status"}))
        self.assertEqual(result["error"], "service_unavailable")

    def test_catalog_schema_fields_are_not_redacted(self):
        self.client.get_json.return_value = {
            "data": [
                {
                    "id": "svc_future",
                    "requires_authorization": True,
                    "configuration_schema": {
                        "properties": {
                            "max_tokens": {"type": "integer"},
                            "secret_name": {"type": "string"},
                        }
                    },
                }
            ]
        }
        result = json.loads(tool.services({"action": "catalog_services"}))
        self.assertTrue(result["data"][0]["requires_authorization"])
        self.assertIn("secret_name", result["data"][0]["configuration_schema"]["properties"])

    def test_provider_credential_fields_are_removed_from_tool_output(self):
        self.client.get_json.return_value = {
            "id": "resource_123456789",
            "status": "complete",
            "access_configuration": {"TOKEN": "private-fixture-value"},
            "details": [{"client_secret": "another-private-value", "name": "safe"}],
        }
        result = json.loads(
            tool.services({"action": "resource", "resource_id": "resource_123456789"})
        )
        self.assertEqual(result["id"], "resource_123456789")
        self.assertEqual(result["details"], [{"name": "safe"}])
        self.assertNotIn("private-fixture-value", json.dumps(result))
        self.assertNotIn("another-private-value", json.dumps(result))

    def test_project_credentials_are_decrypted_only_on_computer(self):
        secret = "provider-secret-never-in-tool-output"

        data = {
            "resource_access_configurations": [
                {"resource_id": "resource_123456789", "access_configuration": {"TOKEN": secret}}
            ]
        }

        def encrypted_reply(_path, payload):
            public_key = serialization.load_pem_public_key(payload["public_key_pem"].encode())
            digest = hashlib.sha256(
                public_key.public_bytes(
                    serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            ).hexdigest()
            project_id = "project_1234567890abcdef"
            aad = f"tinyhat-stripe-project-v1:{project_id}:{digest}"
            key = os.urandom(32)
            nonce = os.urandom(12)
            encrypted = AESGCM(key).encrypt(
                nonce,
                json.dumps({"stripe_environment_info": json.dumps(data)}).encode(),
                aad.encode(),
            )
            wrapped = public_key.encrypt(
                key,
                padding.OAEP(
                    mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None
                ),
            )
            return {
                "project_id": project_id,
                "envelope": {
                    "algorithm": "RSA-OAEP-256+A256GCM",
                    "key_fingerprint": digest,
                    "aad": aad,
                    "wrapped_key": base64.b64encode(wrapped).decode(),
                    "nonce": base64.b64encode(nonce).decode(),
                    "ciphertext": base64.b64encode(encrypted).decode(),
                },
            }

        self.client.post_json.side_effect = encrypted_reply
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(environment, "_private_directory", return_value=Path(directory)),
        ):
            result = json.loads(tool.services({"action": "sync_environment"}))
            self.assertEqual(result["project_id"], "project_1234567890abcdef")
            self.assertEqual(result["resource_count"], 1)
            self.assertNotIn(secret, json.dumps(result))
            saved = Path(result["credential_file"])
            self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
            self.assertIn(secret, saved.read_text())
        self.client.post_json.assert_called_once()
        data = ["invalid Stripe credential payload"]
        result = json.loads(tool.services({"action": "sync_environment"}))
        self.assertEqual(result["error"], "service_unavailable")


if __name__ == "__main__":
    unittest.main()
