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
        with self.assertRaises(RuntimeError):
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
