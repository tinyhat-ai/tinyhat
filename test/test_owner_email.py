"""Owner-only submission, safe sender authentication and restart persistence."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tinyhat.capabilities.mail import owner
from tinyhat.capabilities.mail.channel_state import InboxState, authenticated_owner


class OwnerMailTests(unittest.TestCase):
    def test_recipient_binding_and_no_header_expansion(self):
        status = {"owner_email": "owner@example.com"}
        with patch.object(owner, "request", return_value=status) as request:
            for args in (
                {"to": ["other@example.com"]},
                {"cc": ["owner@example.com"]},
                {"bcc": ["other@example.com"]},
                {"attachments": [{}]},
            ):
                with self.assertRaises(ValueError):
                    owner.send_owner(args)
            owner.send_owner(
                {
                    "to": "owner@example.com",
                    "subject": "Hello",
                    "body": "Hi",
                    "idempotency_key": "reply-123",
                }
            )
            sent = request.call_args.args[1]
            self.assertNotIn("to", sent)
            self.assertNotIn("from", sent)
            self.assertEqual(sent["idempotency_key"], "reply-123")

    def test_send_forwards_reply_header_only_when_present(self):
        with patch.object(owner, "request", return_value={"status": "sent", "owner_email": "owner@example.test"}) as request:
            owner.send_owner({"subject": "Reply", "body": "Hello", "in_reply_to": "<parent@example.test>"})
            self.assertEqual(request.call_args.args[1]["in_reply_to"], "<parent@example.test>")
            owner.send_owner({"subject": "New message", "body": "Hello"})
            self.assertNotIn("in_reply_to", request.call_args.args[1])

    def test_rename_requires_explicit_notice_acknowledgement(self):
        with patch.object(owner, "request", return_value={"status": "ready"}) as request:
            result = json.loads(
                owner.email_address({"action": "confirm", "confirmation_token": "fixture"})
            )
            self.assertEqual(result["status"], "error")
            request.assert_not_called()
            owner.email_address(
                {
                    "action": "confirm",
                    "confirmation_token": "fixture",
                    "acknowledge_old_address_expires_in_24_hours": True,
                }
            )
            self.assertEqual(request.call_args.args[0], "rename/confirm")

    def test_owner_from_is_not_enough_and_lower_forged_results_do_not_authorize(self):
        m = {"from": [{"email": "owner@example.com"}], "header:From:all": ["owner@example.com"]}
        self.assertFalse(authenticated_owner(m, "owner@example.com", "mail.example.com"))
        good = "mail.example.com; dmarc=pass header.from=example.com policy.dmarc=none"
        m["header:Authentication-Results:all"] = [good]
        self.assertTrue(authenticated_owner(m, "owner@example.com", "mail.example.com"))
        m["header:Authentication-Results:all"] = [
            good.replace("mail.example.com;", "mail.example.com 1;")
        ]
        self.assertTrue(authenticated_owner(m, "owner@example.com", "mail.example.com"))
        for values in (
            [good.replace("mail.example.com;", "attacker.example;")],
            [good.replace("header.from=example.com", "header.from=badexample.com")],
            ["mail.example.com; dmarc=fail header.from=example.com", good],
        ):
            m["header:Authentication-Results:all"] = values
            self.assertFalse(authenticated_owner(m, "owner@example.com", "mail.example.com"))
        m["header:Authentication-Results:all"] = [good]
        m["from"].append({"email": "other@example.com"})
        self.assertFalse(authenticated_owner(m, "owner@example.com", "mail.example.com"))

    def test_safe_platform_limit_is_explained_without_provider_text(self):
        exc = owner.PlatformError(
            "secret provider response",
            status_code=429,
            response={
                "error": {"code": "email_send_limit", "retry_after": 3600, "message": "private"}
            },
        )
        result = json.loads(owner.platform_error_json("tinyhat_mail", exc))
        self.assertEqual(result["error"], "email_send_limit")
        self.assertEqual(result["expected"]["retry_after_seconds"], 3600)
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("secret", json.dumps(result))

    def test_authentication_claims_in_comments_or_quoted_text_never_authorize(self):
        good = "mail.example.com; dmarc=pass header.from=example.com"
        message = {
            "from": [{"email": "owner@example.com"}],
            "header:From:all": ["owner@example.com"],
        }
        for result in (
            'mail.example.com; spf=fail reason="; dmarc=pass header.from=example.com;"',
            "mail.example.com; spf=fail (outer (nested; dmarc=pass header.from=example.com;))",
            'mail.example.com; dmarc=fail reason="dmarc=pass header.from=example.com"',
            "mail.example.com; dmarc=fail (dmarc=pass) header.from=example.com",
            good + "; dmarc=fail header.from=example.com",
            good + " header.from=attacker.example",
            good.replace("example.com", "example.com.attacker.test"),
            good.replace("mail.example.com;", "mail.example.com 2;"),
            good + ' reason="unterminated',
            good + " (unterminated",
            good + "\x00",
        ):
            with self.subTest(result=result):
                message["header:Authentication-Results:all"] = [result]
                self.assertFalse(
                    authenticated_owner(message, "owner@example.com", "mail.example.com")
                )
        message["header:Authentication-Results:all"] = [good, good]
        self.assertFalse(authenticated_owner(message, "owner@example.com", "mail.example.com"))
        message["header:Authentication-Results:all"] = [good]
        message["header:From:all"] *= 2
        self.assertFalse(authenticated_owner(message, "owner@example.com", "mail.example.com"))

    def test_authenticated_other_sender_and_reply_to_owner_are_not_owner_commands(self):
        message = {
            "from": [{"email": "other@example.com"}],
            "replyTo": [{"email": "owner@example.com"}],
            "header:From:all": ["Owner <other@example.com>"],
            "header:Authentication-Results:all": [
                "mail.example.com; dmarc=pass header.from=example.com"
            ],
        }
        self.assertFalse(authenticated_owner(message, "owner@example.com", "mail.example.com"))

    def test_receiver_grammar_requires_ascii_and_a_final_dmarc_verdict(self):
        good = "mail.example.test; dmarc=pass header.from=example.tesk"
        message = {
            "from": [{"email": "owner@example.tesk"}],
            "header:From:all": ["owner@example.tesk"],
        }
        for result in (
            good + "; spf=pass smtp.mailfrom=example.tesk",
            good.replace("pass header", "pass\u00a0header"),
            good.replace("example.tesk", "example.tes\u212a"),
            good.replace("mail.example.test", "mail.example.te\u017ft"),
        ):
            with self.subTest(result=result):
                message["header:Authentication-Results:all"] = [result]
                self.assertFalse(
                    authenticated_owner(message, "owner@example.tesk", "mail.example.test")
                )
        message["header:Authentication-Results:all"] = [good]
        self.assertTrue(authenticated_owner(message, "owner@example.tesk", "mail.example.test"))

    def test_outbox_and_processed_ids_survive_restart_privately(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "mail" / "state.sqlite3"
            state = InboxState(p)
            state.put("welcome", "done")
            state.put(
                "reply", "outbox", {"body": "Original reply", "idempotency_key": "stable-key"}
            )
            state.close()
            state = InboxState(p)
            self.assertEqual(state.get("welcome")[0], "done")
            self.assertEqual(json.loads(state.pending()[0][3])["body"], "Original reply")
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            state.close()
