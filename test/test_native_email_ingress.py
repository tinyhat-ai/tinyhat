"""Owner authentication and durable handoff to native coding sessions."""

import copy
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from package_support import load_local_tinyhat

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
load_local_tinyhat(Path(__file__).resolve().parents[1])
ingress = importlib.import_module("tinyhat.capabilities.mail.ingress")


class NativeEmailIngressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.channel = {
            "status": "ready",
            "agent_id": "agent-test",
            "owner_email": "owner@example.test",
            "authserv_id": "mx.example.test",
        }
        self.client = Mock(account_id="account")
        self.client.call.return_value = {
            "methodResponses": [["Email/query", {"queryState": "cursor", "ids": []}, "q"]]
        }
        self.client.call.side_effect = lambda calls: {
            "methodResponses": [[calls[0][0], {"queryState": "cursor", "newQueryState": "cursor", "ids": [], "added": []}, "q"]]
        }
        self.patches = [
            patch.dict(
                os.environ,
                {
                    "HERMES_HOME": self.temp.name,
                    "TINYHAT_EMAIL_CHANNEL_CREATED_AT": "2026-01-01T00:00:00Z",
                },
            ),
            patch.object(ingress.owner, "request", return_value=self.channel),
            patch.object(ingress, "_discover_session", return_value=(self.client, None)),
            patch.object(ingress, "_mailbox_id_by_role", return_value="inbox"),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.inbox = ingress.OwnerInbox()
        self.addCleanup(self.inbox.close)
        self.message = {
            "id": "m1",
            "from": [{"email": "owner@example.test"}],
            "header:From:all": ["owner@example.test"],
            "header:Authentication-Results:all": [
                "mx.example.test; dkim=pass header.d=example.test; dmarc=pass header.from=example.test"
            ],
            "subject": "Keep going",
            "messageId": ["message@example.test"],
            "inReplyTo": ["parent@example.test"],
            "textBody": [{"partId": "plain"}],
            "bodyValues": {"plain": {"value": "Hello — 世界"}},
        }

    def enqueue(self, message):
        self.inbox.state.ingest([message], {})

    def test_committed_native_receipt_precedes_mailbox_completion(self):
        self.enqueue(self.message)
        accepted = []
        self.inbox.poll(lambda key, value: accepted.append((key, value)))
        self.assertEqual(accepted[0][0], "email:m1")
        self.assertEqual(accepted[0][1]["text"], "Hello — 世界")
        self.assertEqual(accepted[0][1]["reply_to"], ["parent@example.test"])
        self.assertEqual(self.inbox.state.get("m1")[0], "done")

    def test_failed_native_commit_remains_queued_for_recovery(self):
        self.enqueue(self.message)
        self.inbox.poll(Mock(side_effect=RuntimeError("disk full")))
        self.assertEqual(self.inbox.state.get("m1")[0], "queued")

    def test_spoofed_owner_and_automatic_mail_never_reach_agent(self):
        for changes in (
            {"header:Authentication-Results:all": []},
            {
                "header:Authentication-Results:all": [
                    "mx.example.test; dmarc=fail header.from=example.test"
                ]
            },
            {"from": [{"email": "someone@example.test"}]},
            {"header:Auto-Submitted:asText": "auto-replied"},
        ):
            message = copy.deepcopy(self.message)
            message.update(changes, id="reject-" + str(len(changes)) + str(changes))
            self.enqueue(message)
        accept = Mock()
        self.inbox.poll(accept)
        accept.assert_not_called()

    def test_reassigned_mailbox_fails_closed(self):
        self.enqueue(self.message)
        with patch.object(
            ingress.owner, "request", return_value={**self.channel, "agent_id": "another-agent"}
        ), self.assertRaises(ValueError):
            self.inbox.poll(Mock())

    def test_poison_arrival_does_not_starve_later_mail_and_retries_are_bounded(self):
        self.enqueue(self.message)
        self.enqueue({**self.message, "id": "healthy"})
        accepted = []
        def accept(key, value):
            if key == "email:m1":
                raise ValueError("private provider text")
            accepted.append(key)
        with self.assertLogs(ingress.logger, level="WARNING") as logs:
            for _ in range(5):
                self.inbox.state.db.execute("UPDATE messages SET retry_at=0")
                self.inbox.state.db.commit()
                self.inbox.state.ingest([], {})
                self.inbox.poll(accept)
        self.assertEqual(accepted, ["email:healthy"])
        self.assertEqual(self.inbox.state.get("m1")[0], "failed")
        self.assertNotIn("private provider text", " ".join(logs.output))
        self.assertEqual(self.inbox.state.db.execute(
            "SELECT turn_attempts,error FROM messages WHERE id='m1'"
        ).fetchone(), (5, "native_handoff_failed"))

    def test_capacity_backpressure_preserves_mail_until_inbox_has_room(self):
        self.enqueue(self.message)
        accept = Mock(side_effect=BufferError("full"))
        # More retries than the poison-message budget, spread over ten minutes.
        start = 2000000000
        with patch("time.time", return_value=start):
            for minute in range(10):
                with patch("time.time", return_value=start + minute * 60):
                    self.inbox.poll(accept)
                    self.inbox.poll(accept)  # backoff suppresses a rapid repeat
            self.assertEqual(accept.call_count, 10)
            self.assertEqual(self.inbox.state.get("m1")[0], "queued")
            self.assertEqual(self.inbox.state.db.execute(
                "SELECT turn_attempts FROM messages WHERE id='m1'"
            ).fetchone()[0], 0)
            accept.side_effect = None
            with patch("time.time", return_value=start + 600):
                self.inbox.poll(accept)
        self.assertEqual(self.inbox.state.get("m1")[0], "done")

    def test_failed_handoff_waits_before_retry(self):
        self.enqueue(self.message)
        accept = Mock(side_effect=ValueError("bad"))
        with self.assertLogs(ingress.logger, level="WARNING"):
            self.inbox.poll(accept)
            self.inbox.poll(accept)
        self.assertEqual(accept.call_count, 1)

    def test_interrupted_hermes_turn_is_recorded_without_replaying_actions(self):
        self.inbox.state.put("old", "processing", {"authenticated_message": self.message})
        self.inbox.state.db.execute("UPDATE messages SET updated=0 WHERE id='old'")
        self.inbox.state.db.commit()
        accept = Mock()
        with self.assertLogs(ingress.logger, level="WARNING") as logs:
            self.inbox.poll(accept)
        accept.assert_not_called()
        self.assertEqual(self.inbox.state.get("old")[0], "failed")
        self.assertIn("framework_switch_interrupted_turn", " ".join(logs.output))
        self.assertEqual(self.inbox.state.arrivals(600), [])

    def test_auto_submitted_no_is_case_insensitive(self):
        for i, value in enumerate((None, "", "no", "No", "NO")):
            self.enqueue({**self.message, "id": str(i), "header:Auto-Submitted:asText": value})
        accept = Mock()
        self.inbox.poll(accept)
        self.assertEqual(accept.call_count, 5)

    def test_platform_timestamp_is_normalized_for_jmap(self):
        with patch.dict(os.environ, {"TINYHAT_EMAIL_CHANNEL_CREATED_AT": "2026-01-01T00:00:00+00:00"}):
            self.inbox.poll(Mock())
        self.assertEqual(self.client.call.call_args.args[0][0][1]["filter"]["after"], "2026-01-01T00:00:00Z")
