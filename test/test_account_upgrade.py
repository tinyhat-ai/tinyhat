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

import tinyhat
from test_hermes_adapter import FakeHermesContext
from tinyhat import context, schemas
from tinyhat.capabilities.account_upgrade import tool
from tinyhat.platform import PlatformError


class AccountUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.base_url = "https://api.tinyhat.ai"
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
        env_patch = patch.object(tool, "runtime_env", return_value={})
        self.runtime_env = env_patch.start()
        self.addCleanup(env_patch.stop)

    def payload(self):
        return {
            "action": "prepare",
            "individual": {"given_name": "Synthetic"},
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
                "revision": None,
            },
        )
        self.builder.assert_called_with(timeout_seconds=45)

    def test_agent_cannot_supply_consent_or_an_approval_action(self):
        for field in ("consent", "human_authorized", "approved"):
            result = json.loads(tool.account_upgrade({**self.payload(), field: True}))
            self.assertEqual(result["error"], "invalid_arguments")
        for action in ("submit", "approve"):
            self.assertEqual(
                json.loads(tool.account_upgrade({"action": action}))["error"], "invalid_action"
            )
        self.builder.assert_not_called()

    def test_review_button_is_sent_without_details_and_keeps_link_for_other_channels(self):
        revision = "thur_" + "a" * 32
        url = f"https://computer.tinyhat.ai/tinyhat/account/upgrade?review={revision}"
        self.client.post_json.return_value = {
            "status": "awaiting_approval",
            "revision": revision,
            "approval_url": url,
            "individual": {"given_name": "private"},
        }
        with (
            patch("tinyhat.tools._telegram_credentials", return_value=("test-token", "test-chat")),
            patch("tinyhat.tools._telegram_send_message", return_value={"ok": True}) as send,
        ):
            result = json.loads(tool.account_upgrade(self.payload()))
        self.assertTrue(result["telegram_button_sent"])
        self.assertEqual(result["approval_url"], url)
        self.assertNotIn("individual", result)
        self.assertEqual(
            send.call_args.kwargs["reply_markup"]["inline_keyboard"][0][0],
            {"text": "Review account upgrade", "url": url},
        )
        self.assertNotIn("private", send.call_args.kwargs["text"])

    def test_review_url_and_revision_are_validated(self):
        revision = "thur_" + "a" * 32
        for url in (
            "https://evil.example/",
            "https://computer.tinyhat.ai/tinyhat/account/upgrade?review=wrong",
            "javascript:alert(1)",
            f"https://computer.tinyhat.ai/tinyhat/account/upgrade;x?review={revision}",
            f"https://computer.tinyhat.ai.evil.example/tinyhat/account/upgrade?review={revision}",
        ):
            self.client.get_json.return_value = {
                "status": "awaiting_approval",
                "revision": revision,
                "approval_url": url,
            }
            result = json.loads(tool.account_upgrade({"action": "status"}))
            self.assertEqual(result["error"], "invalid_platform_response")

    def draft(self, origin="https://computer.tinyhat.ai"):
        revision = "thur_" + "a" * 32
        return {
            "status": "awaiting_approval",
            "revision": revision,
            "approval_url": f"{origin}/tinyhat/account/upgrade?review={revision}",
        }

    def test_separate_web_origin_requires_runtime_configuration(self):
        self.client.base_url = "https://api.example.test"
        self.client.get_json.return_value = self.draft("https://app.example.test")
        self.assertEqual(json.loads(tool.account_upgrade())["error"], "invalid_platform_response")
        self.runtime_env.return_value = {
            "TINYHAT_ACCOUNT_REVIEW_ORIGIN": "https://app.example.test"
        }
        self.assertEqual(json.loads(tool.account_upgrade())["status"], "awaiting_approval")
        self.client.get_json.return_value = self.draft("https://other.example.test")
        self.assertEqual(json.loads(tool.account_upgrade())["error"], "invalid_platform_response")

    def test_invalid_runtime_origin_cannot_expand_trust(self):
        self.client.get_json.return_value = self.draft("https://app.example.test")
        for origin in (
            "http://app.example.test", "https://user@app.example.test",
            "https://app.example.test/path", "https://app.example.test#fragment",
            "https://app.example.test:444", "https://app.example.test?x=y",
        ):
            with self.subTest(origin=origin):
                self.runtime_env.return_value = {"TINYHAT_ACCOUNT_REVIEW_ORIGIN": origin}
                self.assertEqual(json.loads(tool.account_upgrade())["error"], "invalid_platform_response")

    def test_status_accepts_platform_host_without_sending_button(self):
        self.client.get_json.return_value = self.draft(self.client.base_url)
        with patch.object(tool, "_send_review_button") as send:
            result = json.loads(tool.account_upgrade())
        self.assertEqual(result["status"], "awaiting_approval")
        send.assert_not_called()

    def test_review_link_gets_existing_draft_and_sends_button(self):
        self.client.get_json.return_value = self.draft()
        with patch.object(tool, "_send_review_button", return_value=True) as send:
            result = json.loads(tool.account_upgrade({"action": "review_link"}))
        self.client.get_json.assert_called_once_with(f"{tool.BASE}/upgrade")
        self.client.post_json.assert_not_called()
        send.assert_called_once_with(result["approval_url"], mini_app_url=None)
        self.assertTrue(result["telegram_button_sent"])

    def test_review_opens_owner_authenticated_mini_app(self):
        draft = self.draft()
        mini_url = f"https://use.tinyloop.co/tinyhat/miniapp/agents/123/account/upgrade?review={draft['revision']}"
        self.client.get_json.return_value = {**draft, "mini_app_url": mini_url}
        with (
            patch("tinyhat.tools._telegram_credentials", return_value=("test-token", "test-chat")),
            patch("tinyhat.tools._telegram_send_message", return_value={"ok": True}) as send,
        ):
            result = json.loads(tool.account_upgrade({"action": "review_link"}))
        self.assertTrue(result["telegram_button_sent"])
        self.assertEqual(send.call_args.kwargs["reply_markup"]["inline_keyboard"][0][0], {
            "text": "Review account upgrade", "web_app": {"url": mini_url}
        })
        self.assertEqual(result["approval_url"], draft["approval_url"])

    def test_invalid_mini_app_link_cannot_send_button(self):
        draft = self.draft()
        path = "/tinyhat/miniapp/agents/123/account/upgrade"
        query = f"?review={draft['revision']}"
        for url in (
            f"https://evil.example{path}{query}",
            f"https://use.tinyloop.co.evil.example{path}{query}",
            f"http://use.tinyloop.co{path}{query}",
            f"https://user@use.tinyloop.co{path}{query}",
            f"https://:password@use.tinyloop.co{path}{query}",
            f"https://use.tinyloop.co:444{path}{query}",
            f"https://use.tinyloop.co:invalid{path}{query}",
            f"https://use.tinyloop.co{path}/{query}",
            f"https://use.tinyloop.co/tinyhat/account/upgrade?review={draft['revision']}",
            "https://use.tinyloop.co/tinyhat/miniapp/agents/123/account/upgrade?review=wrong",
            f"https://use.tinyloop.co/tinyhat/miniapp/agents/123/account/upgrade?review={draft['revision']}#token=x",
            "", [], {}, 42, False,
        ):
            with self.subTest(url=url), patch.object(tool, "_send_review_button") as send:
                self.client.get_json.return_value = {**draft, "mini_app_url": url}
                result = json.loads(tool.account_upgrade({"action": "review_link"}))
                self.assertEqual(result["error"], "invalid_platform_response")
                send.assert_not_called()

    def test_null_mini_app_link_keeps_standalone_button(self):
        draft = self.draft()
        self.client.get_json.return_value = {**draft, "mini_app_url": None}
        with patch.object(tool, "_send_review_button", return_value=True) as send:
            result = json.loads(tool.account_upgrade({"action": "review_link"}))
        self.assertEqual(result["approval_url"], draft["approval_url"])
        send.assert_called_once_with(draft["approval_url"], mini_app_url=None)

    def test_telegram_failure_returns_review_url(self):
        self.client.post_json.return_value = self.draft()
        with (
            patch("tinyhat.tools._telegram_credentials", return_value=("test-token", "test-chat")),
            patch("tinyhat.tools._telegram_send_message", side_effect=OSError("private")),
        ):
            result = json.loads(tool.account_upgrade(self.payload()))
        self.assertFalse(result["telegram_button_sent"])
        self.assertEqual(result["approval_url"], self.draft()["approval_url"])
        self.assertNotIn("private", json.dumps(result))

    def test_approval_fields_are_removed_from_other_states(self):
        self.client.get_json.return_value = {
            "status": "pending", "approval_url": "javascript:alert(1)",
            "revision": "untrusted", "approval_expires_at": "untrusted",
        }
        self.assertEqual(json.loads(tool.account_upgrade()), {"status": "pending"})

    def test_correction_sends_current_revision_without_consent(self):
        revision = "thur_" + "a" * 32
        tool.account_upgrade({**self.payload(), "revision": revision})
        self.assertEqual(
            self.client.post_json.call_args.args[1],
            {"individual": self.payload()["individual"], "revision": revision},
        )

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

    def test_verification_link_rejects_non_string_urls_without_raising(self):
        for url in (None, 123, [], {}, True, b"https://connect.stripe.com/private"):
            with self.subTest(url_type=type(url).__name__):
                self.client.post_json.return_value = {"url": url}
                result = tool.account_upgrade({"action": "verification_link"})
                self.assertEqual(json.loads(result)["error"], "invalid_platform_response")
                self.assertNotIn("private", result)

    def test_local_token_does_not_masquerade_as_cloud_identity(self):
        self.builder.return_value = (self.client, "local_dev")
        self.assertEqual(
            json.loads(tool.account_upgrade({"action": "status"}))["error"],
            "computer_identity_required",
        )
        self.client.get_json.assert_not_called()

    def test_continue_and_verification_routes_are_assignment_scoped(self):
        tool.account_upgrade({"action": "continue"})
        self.client.post_json.assert_called_once_with(f"{tool.BASE}/upgrade/continue", {})
        self.client.post_json.reset_mock()
        self.client.post_json.return_value = {"url": "https://connect.stripe.com/setup/s/fixture"}
        result = json.loads(tool.account_upgrade({"action": "verification_link"}))
        self.client.post_json.assert_called_once_with(f"{tool.BASE}/verification-link", {})
        self.assertEqual(result["url"], "https://connect.stripe.com/setup/s/fixture")

    def test_interrupted_requests_return_safe_recovery_instructions(self):
        from http.client import RemoteDisconnected

        for failure in (TimeoutError, RemoteDisconnected, ConnectionResetError):
            for action in ("prepare", "continue", "verification_link", "status"):
                with self.subTest(failure=failure.__name__, action=action):
                    self.client.get_json.side_effect = failure("private-details")
                    self.client.post_json.side_effect = failure("private-details")
                    payload = self.payload() if action == "prepare" else {"action": action}
                    result = tool.account_upgrade(payload)
                    self.assertNotIn("private-details", result)
                    parsed = json.loads(result)
                    self.assertEqual(
                        parsed["error"],
                        "upgrade_submission_uncertain"
                        if action == "prepare"
                        else "account_upgrade_unavailable",
                    )
                    self.assertIn("status", parsed["message"])
        self.assertEqual(self.client.post_json.call_count, 9)
        self.assertEqual(self.client.get_json.call_count, 3)

    def test_machine_owner_and_http_failures_are_actionable_without_raw_details(self):
        cases = [
            (401, None, "computer_authentication_required"),
            (403, None, "computer_authentication_required"),
            (422, None, "invalid_request"),
            (403, "computer_owner_unavailable", "computer_owner_unavailable"),
            (403, "computer_owner_changed", "computer_owner_changed"),
            (409, "upgrade_already_submitted", "account_upgrade_conflict"),
            (409, "verification_not_required", "account_upgrade_conflict"),
            (429, None, "account_upgrade_rate_limited"),
        ]
        for status, code, expected in cases:
            with self.subTest(status=status, code=code):
                self.client.post_json.side_effect = PlatformError(
                    "private-details",
                    status_code=status,
                    response={"error": {"code": code, "message": "private-details"}},
                )
                result = tool.account_upgrade(self.payload())
                self.assertNotIn("private-details", result)
                self.assertEqual(json.loads(result)["error"], expected)
                if status in (409, 429) and code not in {
                    "computer_owner_unavailable",
                    "computer_owner_changed",
                }:
                    self.assertIn("status", json.loads(result)["message"])

    def test_disabled_status_is_preserved(self):
        self.client.get_json.return_value = {"status": "not_started", "available": False}
        self.assertEqual(
            json.loads(tool.account_upgrade({"action": "status"})),
            {"status": "not_started", "available": False},
        )
        self.client.post_json.assert_not_called()

    def test_unrelated_account_upgrades_do_not_route_to_tinyhat(self):
        for phrase in (
            "Please upgrade my account on GitHub",
            "upgrade my account to Spotify premium",
        ):
            self.assertFalse(context.should_inject_tinyhat_context(phrase))
        for phrase in (
            "upgrade my Tinyhat account",
            "enable Stripe Projects",
            "upgrade the owner account",
        ):
            self.assertTrue(context.should_inject_tinyhat_context(phrase))
            self.assertIn(
                "tinyhat:tinyhat-account-upgrade",
                context._compose_onboarding_context(context.TINYHAT_CONTEXT, phrase),
            )

    def test_context_retains_existing_playbooks_and_plugin_update_onboarding(self):
        self.assertLessEqual(len(context.TINYHAT_CONTEXT), 10000)
        for skill in (
            "tinyhat-platform",
            "tinyhat-private-secret",
            "tinyhat-skill-catalog",
            "tinyhat-plugin-version",
        ):
            self.assertIn("tinyhat:" + skill, context.TINYHAT_CONTEXT)
        onboarding = context._compose_onboarding_context(context.TINYHAT_CONTEXT, "hi")
        self.assertIn("If this Computer reports update_available=true", onboarding)
        self.assertLessEqual(len(onboarding), 9500)

    def test_invalid_action_types_are_rejected_without_network(self):
        for action in ([], {}, 1, None):
            self.assertEqual(
                json.loads(tool.account_upgrade({"action": action}))["error"], "invalid_action"
            )
        self.builder.assert_not_called()
