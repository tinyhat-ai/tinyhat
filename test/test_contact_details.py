"""Tests for Tinyhat managed contact details."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))
from package_support import load_local_tinyhat  # noqa: E402

load_local_tinyhat(REPO_ROOT)

from tinyhat.capabilities.contact_details import tool as contact_details  # noqa: E402
from tinyhat.platform import PlatformError  # noqa: E402


class ContactDetailsToolTests(unittest.TestCase):
    def test_reads_safe_contacts_from_attested_computer_route(self) -> None:
        original_build = contact_details.build_platform_client
        calls: list[tuple[str, dict[str, object]]] = []

        class FakeClient:
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                calls.append((path, payload))
                return {
                    "schema": "tinyhat_agent_contact_details_v1",
                    "phone": {
                        "status": "assigned",
                        "phone_number": "+12045550123",
                        "credential_reference": "must-not-leak",
                        "provider_account": "must-not-leak",
                    },
                    "email": {
                        "status": "disabled",
                        "email_address": None,
                    },
                    "agent_id": 91,
                }

        try:
            contact_details.build_platform_client = lambda: (FakeClient(), "gcloud")
            payload = json.loads(contact_details.contact_details())
        finally:
            contact_details.build_platform_client = original_build

        self.assertEqual(calls, [("/hapi/v1/computers/me/contact-details/v1", {})])
        self.assertEqual(payload["phone"]["phone_number"], "+12045550123")
        self.assertEqual(payload["email"], {"status": "disabled", "email_address": None})
        serialized = json.dumps(payload)
        self.assertNotIn("credential_reference", serialized)
        self.assertNotIn("provider_account", serialized)
        self.assertNotIn("agent_id", serialized)

    def test_uses_local_computer_route(self) -> None:
        original_build = contact_details.build_platform_client
        paths: list[str] = []

        class FakeClient:
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                paths.append(path)
                self.assert_payload = payload
                return {
                    "phone": {"status": "not_available", "phone_number": None},
                    "email": {"status": "assigned", "email_address": "agent@tinyhat.ai"},
                }

        try:
            contact_details.build_platform_client = lambda: (FakeClient(), "local_dev")
            payload = json.loads(contact_details.contact_details())
        finally:
            contact_details.build_platform_client = original_build

        self.assertEqual(paths, ["/hapi/v1/computers/local-dev/contact-details/v1"])
        self.assertEqual(payload["email"]["email_address"], "agent@tinyhat.ai")

    def test_rejects_malformed_platform_status(self) -> None:
        original_build = contact_details.build_platform_client

        class FakeClient:
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                _ = (path, payload)
                return {
                    "phone": {"status": "secret", "phone_number": "+12045550123"},
                    "email": {"status": "disabled", "email_address": None},
                }

        try:
            contact_details.build_platform_client = lambda: (FakeClient(), "gcloud")
            payload = json.loads(contact_details.contact_details())
        finally:
            contact_details.build_platform_client = original_build

        self.assertEqual(payload["error"], "invalid_platform_response")

    def test_platform_errors_do_not_echo_details(self) -> None:
        original_build = contact_details.build_platform_client

        def fail() -> tuple[object, str]:
            raise PlatformError(
                "AgentPhone key secret-value failed",
                status_code=503,
                response={"detail": "credential_reference=must-not-leak"},
            )

        try:
            contact_details.build_platform_client = fail
            payload = json.loads(contact_details.contact_details())
        finally:
            contact_details.build_platform_client = original_build

        self.assertEqual(payload["error"], "contact_details_unavailable")
        serialized = json.dumps(payload)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("credential_reference", serialized)

    def test_skill_uses_plain_language_and_requires_no_confirmation(self) -> None:
        skill = (REPO_ROOT / "skills" / "tinyhat-contact-details" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("needs no user confirmation", skill)
        self.assertIn("phone number", skill)
        self.assertIn("email address", skill)
        self.assertNotIn("OpenClaw", skill)


if __name__ == "__main__":
    unittest.main()
