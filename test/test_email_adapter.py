"""Exercise the adapter without importing an installed gateway in package CI."""

import asyncio
import importlib.util
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError

from tinyhat.capabilities.mail import owner
from tinyhat.capabilities.mail.channel_state import InboxState
from tinyhat.capabilities.mail.tool import MailboxError


class FakeBase:
    def __init__(self, config, platform):
        self.platform = platform
        self.handle_message = AsyncMock()
        self.cancel_background_tasks = AsyncMock()

    def set_busy_session_handler(self, handler):
        self.busy_handler = handler

    def _mark_connected(self):
        self._running = True

    def _mark_disconnected(self):
        self._running = False


class Event:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


@dataclass
class Result:
    success: bool
    message_id: str = None
    error: str = None


def load_adapter():
    modules = {}
    for name in (
        "gateway",
        "gateway.config",
        "gateway.platforms",
        "gateway.platforms.base",
        "gateway.session",
    ):
        modules[name] = types.ModuleType(name)
    modules["gateway.config"].Platform = str
    base = modules["gateway.platforms.base"]
    base.BasePlatformAdapter, base.MessageEvent, base.SendResult = FakeBase, Event, Result
    modules["gateway.session"].SessionSource = Event
    path = Path(owner.__file__).with_name("channel.py")
    spec = importlib.util.spec_from_file_location("tinyhat.capabilities.mail._tested_channel", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


channel = load_adapter()


class EmailAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.adapter = channel.TinyhatEmailAdapter({})
        self.adapter._state = InboxState(Path(self.temp.name) / "state.sqlite3")
        self.addCleanup(self.adapter._state.close)
        self.adapter._channel = {
            "address": "agent@example.test",
            "owner_email": "owner@example.test",
            "authserv_id": "mx.example.test",
            "agent_id": "agent-fixture",
        }
        self.adapter._authserv_id = "mx.example.test"
        self.adapter._created_at = "2026-01-01T00:00:00Z"
        self.adapter._inbox_id = "inbox-fixture"
        self.sent = []

    def deliver(self, action, payload):
        self.assertEqual(action, "send")
        self.sent.append(payload)
        return {"status": "sent", "message_id": "receipt"}

    def test_email_uses_sdk_queue_instead_of_chat_interrupt_handler(self):
        self.adapter.set_busy_session_handler(AsyncMock())
        self.assertIsNone(self.adapter.busy_handler)

    async def test_two_queued_turns_keep_their_own_reply_identity(self):
        """The drain task inherits turn one's context, like the real SDK."""
        queued = asyncio.Event()
        pending = []
        worker = None

        async def process(event):
            await self.adapter.send(
                "owner", event.text, reply_to=event.message_id, metadata={"notify": True}
            )
            await self.adapter.on_processing_complete(event, "success")

        async def drain(first):
            await process(first)
            await queued.wait()  # Session remains busy after processing_complete.
            await process(pending.pop())

        async def handle(event):
            nonlocal worker
            if worker is None:
                worker = asyncio.create_task(drain(event))
            else:
                pending.append(event)
                queued.set()

        self.adapter.handle_message = handle
        with patch.object(owner, "request", side_effect=self.deliver):
            await asyncio.wait_for(
                self.adapter._dispatch(
                    "one", {"subject": "First", "in_reply_to": "<one@example.test>"}, "First body"
                ),
                2,
            )
            await asyncio.wait_for(
                self.adapter._dispatch(
                    "two", {"subject": "Second", "in_reply_to": "<two@example.test>"}, "Second body"
                ),
                2,
            )
            await worker
        self.assertEqual([p["subject"] for p in self.sent], ["First", "Second"])
        self.assertEqual(self.sent[1]["in_reply_to"], "<two@example.test>")
        self.assertNotEqual(self.sent[0]["idempotency_key"], self.sent[1]["idempotency_key"])

    async def test_empty_welcome_remains_retryable_and_dropped_event_is_bounded(self):
        async def empty(event):
            await self.adapter.on_processing_complete(event, "success")

        self.adapter.handle_message = empty
        await self.adapter._welcome()
        self.assertEqual(self.adapter._state.get(channel.WELCOME)[0], "processing")
        self.adapter.handle_message = AsyncMock()
        with patch.object(channel, "TURN_WAIT_SECONDS", 0.01):
            await asyncio.wait_for(self.adapter._dispatch("dropped", {"subject": "Later"}, "Hi"), 1)
        self.assertEqual(self.adapter._state.get("dropped")[0], "processing")

    async def test_provider_billing_error_is_not_sent_as_a_welcome(self):
        self.adapter._state.put(channel.WELCOME, "processing", {"metadata": {"welcome": True}})
        with patch.object(owner, "request") as send:
            result = await self.adapter.send(
                "owner",
                "Billing or credits exhausted: HTTP 402 private provider details",
                reply_to=channel.WELCOME,
            )
        self.assertFalse(result.success)
        send.assert_not_called()
        self.assertEqual(self.adapter._state.get(channel.WELCOME)[0], "processing")

    async def test_failed_turn_budget_survives_restart_and_sends_one_fixed_notice(self):
        async def fail(event):
            # The real gateway omits notify on its error notification.
            await self.adapter.send(
                "owner",
                "HTTP 402 private-fixture-secret",
                metadata={"thread_id": "conversation"},
            )
            await self.adapter.on_processing_complete(event, "error")

        self.adapter.handle_message = AsyncMock(side_effect=fail)
        metadata = {"subject": "Re: Question", "in_reply_to": "<question@example.test>"}
        restart_after = 3
        with patch.object(owner, "request", side_effect=self.deliver):
            for attempt in range(channel.MAX_TURN_ATTEMPTS + 3):
                if attempt == restart_after:
                    self.adapter._state.close()
                    self.adapter._state = InboxState(Path(self.temp.name) / "state.sqlite3")
                    self.addCleanup(self.adapter._state.close)
                await self.adapter._dispatch("question", metadata, "Help me", internal=False)
                await self.adapter._recover_outbox()
        self.assertEqual(self.adapter.handle_message.await_count, channel.MAX_TURN_ATTEMPTS)
        self.assertEqual(self.adapter._state.get("question")[0], "failed")
        self.assertEqual(self.adapter._state.arrivals(0), [])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["in_reply_to"], "<question@example.test>")
        self.assertIn("stopped retrying", self.sent[0]["body"])
        self.assertNotIn("private-fixture", self.sent[0]["body"])
        self.assertNotIn("welcome", self.sent[0])
        # A late completion cannot replace the notice with another reply.
        self.assertFalse(
            (await self.adapter.send("owner", "Late answer", reply_to="question")).success
        )

    async def test_exhausted_welcome_does_not_claim_success_or_block_new_owner_mail(self):
        async def empty(event):
            await self.adapter.on_processing_complete(event, "error")

        self.adapter.handle_message = AsyncMock(side_effect=empty)
        with (
            patch.object(channel.time, "time", return_value=100_000) as clock,
            patch.object(owner, "request", side_effect=self.deliver),
        ):
            for _ in range(channel.MAX_TURN_ATTEMPTS + 3):
                await self.adapter._welcome()
                await self.adapter._recover_outbox()
                clock.return_value += channel.RETRY_TURN_SECONDS + 1
        self.assertEqual(self.adapter.handle_message.await_count, channel.MAX_TURN_ATTEMPTS)
        self.assertEqual(self.adapter._state.get(channel.WELCOME)[0], "failed")
        self.assertFalse(self.adapter._channel.get("welcome_sent_at"))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("couldn't finish the welcome", self.sent[0]["body"])
        self.assertNotEqual(self.sent[0]["idempotency_key"], channel.WELCOME)

        async def recovered(event):
            await self.adapter.send("owner", "I'm ready to help.", reply_to=event.message_id)

        self.adapter.handle_message = recovered
        with patch.object(owner, "request", side_effect=self.deliver):
            await self.adapter._dispatch("new-question", {"subject": "Re: Try again"}, "Hello")
        self.assertEqual(self.adapter._state.get("new-question")[0], "done")
        self.assertEqual(len(self.sent), 2)

    async def test_model_recovery_keeps_separate_full_smtp_retry_budget(self):
        async def empty(event):
            await self.adapter.on_processing_complete(event, "error")

        self.adapter.handle_message = empty
        for _ in range(channel.MAX_TURN_ATTEMPTS - 1):
            await self.adapter._dispatch("slow", {"subject": "Re: Question"}, "Help")

        async def recovered(event):
            await self.adapter.send("owner", "Recovered answer", reply_to=event.message_id)
            await self.adapter.on_processing_complete(event, "success")

        self.adapter.handle_message = recovered
        error = owner.PlatformError("private", status_code=429)
        with patch.object(owner, "request", side_effect=error):
            await self.adapter._dispatch("slow", {"subject": "Re: Question"}, "Help")
            self.assertEqual(self.adapter._state.get("slow")[0], "outbox")
            payload = json.loads(self.adapter._state.get("slow")[2])
            for _ in range(channel.MAX_DELIVERY_ATTEMPTS - 2):
                await self.adapter._deliver("slow", payload)
                self.assertEqual(self.adapter._state.get("slow")[0], "outbox")
            await self.adapter._deliver("slow", payload)
        self.assertEqual(self.adapter._state.get("slow")[0], "failed")
        self.assertEqual(
            self.adapter._state.db.execute(
                "SELECT turn_attempts,attempts FROM messages WHERE id='slow'"
            ).fetchone(),
            (channel.MAX_TURN_ATTEMPTS, channel.MAX_DELIVERY_ATTEMPTS),
        )

    def test_upgrade_adds_turn_budget_without_resetting_existing_delivery_state(self):
        path = Path(self.temp.name) / "previous.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE messages (id TEXT PRIMARY KEY, state TEXT NOT NULL, updated REAL NOT NULL, payload TEXT, attempts INTEGER NOT NULL DEFAULT 0, error TEXT, retry_at REAL NOT NULL DEFAULT 0)"
            )
            db.execute(
                "INSERT INTO messages VALUES ('pending','outbox',10,'{}',3,'email_send_limit',9000)"
            )
        db.close()
        state = InboxState(path)
        self.addCleanup(state.close)
        self.assertEqual(
            state.db.execute(
                "SELECT state,attempts,turn_attempts,error,retry_at FROM messages WHERE id='pending'"
            ).fetchone(),
            ("outbox", 3, 0, "email_send_limit", 9000),
        )

    async def test_autoresponse_self_sender_and_untrusted_owner_spoof(self):
        self.adapter._dispatch = AsyncMock()
        for key, extra in (
            ("auto", {"header:Auto-Submitted:asText": "auto-replied"}),
            ("self", {"from": [{"email": "agent@example.test"}]}),
        ):
            await self.adapter._receive({"id": key, **extra})
            self.assertEqual(self.adapter._state.get(key)[0], "done")
        self.adapter._dispatch.assert_not_awaited()
        await self.adapter._receive(
            {
                "id": "spoof",
                "from": [{"email": "owner@example.test"}],
                "header:From:all": ["owner@example.test"],
                "subject": "untrusted command",
                "textBody": [{"partId": "body"}],
                "bodyValues": {"body": {"value": "Do something dangerous"}},
            }
        )
        self.assertEqual(self.adapter._state.get("spoof")[0], "done")
        for number in range(10):
            await self.adapter._receive(
                {"id": f"spam-{number}", "from": [{"email": "unknown@example.test"}]}
            )
        self.adapter._dispatch.assert_not_awaited()

    async def test_long_message_id_does_not_reject_legitimate_reply(self):
        self.adapter._dispatch = AsyncMock()
        await self.adapter._receive(
            {
                "id": "long",
                "from": [{"email": "owner@example.test"}],
                "header:From:all": ["owner@example.test"],
                "messageId": ["x" * 260 + "@example.test"],
                "header:Authentication-Results:all": [
                    "mx.example.test; dmarc=pass header.from=example.test"
                ],
            }
        )
        self.assertNotIn("in_reply_to", self.adapter._dispatch.call_args.args[1])

    async def test_authentication_drop_logs_are_private_and_rate_limited(self):
        self.adapter._dispatch = AsyncMock()
        message = {
            "id": "private-message-id",
            "from": [{"email": "owner@example.test"}],
            "header:From:all": ["owner@example.test"],
            "subject": "private subject",
            "textBody": [{"partId": "body"}],
            "bodyValues": {"body": {"value": "private body"}},
        }
        with (
            patch.object(channel.logger, "warning") as log,
            patch.object(channel.time, "monotonic", return_value=100) as now,
        ):
            await self.adapter._receive(message)
            self.assertEqual(log.call_args.args[1], "missing_or_ambiguous_authentication_results")
            await self.adapter._receive({**message, "id": "second-private-id"})
            self.assertEqual(log.call_count, 1)
            await self.adapter._resume("legacy-private-id", {})
            self.assertEqual(log.call_count, 2)
            self.assertEqual(log.call_args.args[1:], ("legacy_missing_authentication", 1))
            await self.adapter._resume("repeated-legacy-private-id", {})
            self.assertEqual(log.call_count, 2)
            now.return_value += channel.STATUS_SECONDS
            await self.adapter._resume("another-private-id", {})
            self.assertEqual(log.call_count, 3)
            self.assertEqual(log.call_args.args[1:], ("legacy_missing_authentication", 2))
        self.adapter._dispatch.assert_not_awaited()
        for private in ("private", "owner@example.test"):
            self.assertNotIn(private, str(log.call_args_list))

    async def test_old_queued_header_format_cannot_start_a_turn_after_upgrade(self):
        self.adapter._dispatch = AsyncMock()
        await self.adapter._receive(
            {
                "id": "old-queued",
                "from": [{"email": "owner@example.test"}],
                "header:Authentication-Results:asText:all": [
                    "mx.example.test; dmarc=pass header.from=example.test"
                ],
            }
        )
        self.adapter._dispatch.assert_not_awaited()
        self.assertEqual(self.adapter._state.get("old-queued")[0], "done")

    async def test_restart_does_not_resume_legacy_external_notices_or_old_owner(self):
        self.adapter._dispatch = AsyncMock()
        saved = {"metadata": {"subject": "Inbox notice"}, "text": "legacy notice", "internal": True}
        self.adapter._state.put("legacy", "processing", saved)
        await self.adapter._resume("legacy", saved.copy())
        self.adapter._dispatch.assert_not_awaited()
        self.assertEqual(self.adapter._state.get("legacy")[0], "done")
        source = {
            "from": [{"email": "owner@example.test"}],
            "header:From:all": ["owner@example.test"],
            "header:Authentication-Results:all": [
                "mx.example.test; dmarc=pass header.from=example.test"
            ],
        }
        saved["authenticated_message"] = source
        await self.adapter._resume("valid", saved.copy())
        self.adapter._dispatch.assert_awaited_once()
        self.adapter._dispatch.reset_mock()
        self.adapter._channel["owner_email"] = "new-owner@example.test"
        await self.adapter._resume("old-owner", saved.copy())
        self.adapter._dispatch.assert_not_awaited()
        self.assertEqual(self.adapter._state.get("old-owner")[0], "done")

    async def test_slash_command_reply_releases_waiter_without_completion_hook(self):
        async def handle(event):
            await self.adapter.send("owner", "Command completed.", reply_to=event.message_id)

        self.adapter.handle_message = handle
        with patch.object(owner, "request", side_effect=self.deliver):
            await asyncio.wait_for(
                self.adapter._dispatch("command", {"subject": "Re: Command"}, "/status"), 0.2
            )

    async def test_generic_gateway_error_does_not_forward_raw_exception(self):
        with patch.object(owner, "request", side_effect=self.deliver):
            await self.adapter.send(
                "owner", "Sorry, I encountered an error (PlatformError). private-fixture-secret"
            )
        self.assertNotIn("private-fixture", self.sent[0]["body"])

    async def test_real_answers_about_errors_are_delivered_unchanged(self):
        replies = (
            "HTTP 404 means that page was not found. Check the address.",
            "Rate limited means the server rejected the burst. Space out retries.",
            "Authentication failed means the credentials need checking.",
        )
        with patch.object(owner, "request", side_effect=self.deliver):
            for index, body in enumerate(replies):
                key = "answer-" + str(index)
                self.adapter._state.put(key, "processing", {"metadata": {"subject": "Re: Logs"}})
                result = await self.adapter.send("owner", body, reply_to=key)
                self.assertTrue(result.success)
                self.assertEqual(self.sent[-1]["body"], body)

    async def test_gateway_error_rewrite_is_logged_without_raw_details(self):
        with (
            patch.object(owner, "request", side_effect=self.deliver),
            self.assertLogs(channel.logger, level="WARNING") as logs,
        ):
            await self.adapter.send("owner", "HTTP 402 private-fixture-secret")
        self.assertNotIn("private-fixture", self.sent[0]["body"])
        self.assertNotIn("private-fixture", " ".join(logs.output))
        self.assertIn("screened", " ".join(logs.output))

    async def test_confirmed_failed_receipt_can_retry_without_another_hour_delay(self):
        payload = {"idempotency_key": "failed-fixture", "body": "Reply"}
        self.adapter._state.put("failed", "uncertain", payload)

        def request(action, value=None):
            if action == "deliveries/failed-fixture":
                return {"status": "failed"}
            return self.deliver(action, value)

        with patch.object(owner, "request", side_effect=request) as call:
            await self.adapter._recover_outbox()
        self.assertEqual(call.call_count, 2)
        self.assertEqual(self.adapter._state.get("failed")[0], "done")

    async def test_rename_pending_retries_but_idempotency_conflict_does_not(self):
        payload = {"subject": "Hi", "body": "Hi", "idempotency_key": "pending-fixture"}
        self.adapter._state.put("rename", "outbox", payload)
        error = owner.PlatformError(
            "private", status_code=409, response={"error": {"code": "email_channel_not_ready"}}
        )
        with patch.object(owner, "request", side_effect=error):
            await self.adapter._deliver("rename", payload)
        self.assertEqual(self.adapter._state.get("rename")[0], "outbox")
        with patch.object(owner, "request", side_effect=self.deliver):
            await self.adapter._deliver("rename", payload)
        self.assertEqual(self.adapter._state.get("rename")[0], "done")

    async def test_uncertain_welcome_reconciles_receipt_without_resending(self):
        payload = {"idempotency_key": channel.WELCOME, "body": "Welcome"}
        self.adapter._state.put(channel.WELCOME, "uncertain", payload)
        with patch.object(owner, "request", return_value={"status": "unknown"}) as lookup:
            await self.adapter._recover_outbox()
            lookup.assert_called_once_with("deliveries/" + channel.WELCOME)
            await self.adapter._recover_outbox()
            self.assertEqual(lookup.call_count, 1)
        self.adapter._state.db.execute("UPDATE messages SET retry_at=0")
        self.adapter._state.db.commit()
        with patch.object(owner, "request", return_value={"status": "sent"}) as lookup:
            await self.adapter._recover_outbox()
            lookup.assert_called_once_with("deliveries/" + channel.WELCOME)
        self.assertEqual(self.adapter._state.get(channel.WELCOME)[0], "done")
        self.assertTrue(self.adapter._channel["welcome_sent_at"])

    def test_retry_after_comes_from_http_header(self):
        error = owner.PlatformError(
            "private", status_code=429, response={"error": {"code": "email_send_limit"}}
        )
        error.__cause__ = HTTPError(
            "https://example.test", 429, "limit", {"Retry-After": "3600"}, None
        )
        self.assertEqual(owner.error_details(error), ("email_send_limit", 3600))

    async def test_identical_notifications_are_distinct_and_progress_is_not_mail(self):
        with patch.object(owner, "request", side_effect=self.deliver):
            await self.adapter.send("owner", "Done.")
            await self.adapter.send("owner", "Done.")
            await self.adapter.send("owner", "Working...", metadata={"thread_id": "conversation"})
        self.assertEqual(len(self.sent), 2)
        self.assertNotEqual(self.sent[0]["idempotency_key"], self.sent[1]["idempotency_key"])

    async def test_terminal_and_uncertain_deliveries_do_not_retry_or_starve_outbox(self):
        payload = {"subject": "Hi", "body": "Hi", "idempotency_key": "reply-fixture"}
        self.adapter._state.put("bad", "outbox", payload)
        exc = owner.PlatformError(
            "private provider text",
            status_code=409,
            response={"error": {"code": "email_idempotency_conflict"}},
        )
        with patch.object(owner, "request", side_effect=exc):
            result = await self.adapter._deliver("bad", payload)
        self.assertEqual(result.error, "email_idempotency_conflict")
        self.assertEqual(self.adapter._state.get("bad")[0], "failed")
        self.adapter._state.put("uncertain", "outbox", payload)
        with patch.object(owner, "request", return_value={"status": "unknown"}):
            await self.adapter._deliver("uncertain", payload)
        self.assertEqual(self.adapter._state.get("uncertain")[0], "uncertain")
        self.assertEqual(self.adapter._state.pending(), [])
        self.adapter._state.put("transient", "outbox", payload)
        with patch.object(owner, "request", side_effect=RuntimeError("private")):
            for _ in range(channel.MAX_DELIVERY_ATTEMPTS):
                await self.adapter._deliver("transient", payload)
        self.assertEqual(self.adapter._state.get("transient")[0], "failed")

    async def test_inbox_role_discovery_retries_after_a_missing_folder(self):
        self.adapter._inbox_id = None
        available = False

        def call(methods):
            method, args, tag = methods[0]
            if method == "Mailbox/get":
                rows = [{"id": "real-inbox", "role": "inbox"}] if available else []
                return {"methodResponses": [[method, {"list": rows}, tag]]}
            self.assertEqual(method, "Email/query")
            self.assertEqual(args["filter"]["inMailbox"], "real-inbox")
            return {"methodResponses": [[method, {"ids": [], "queryState": "ready"}, tag]]}

        self.adapter._client = types.SimpleNamespace(account_id="fixture", call=call)
        with self.assertRaisesRegex(MailboxError, "mailbox_not_available"):
            await self.adapter._messages()
        self.assertIsNone(self.adapter._inbox_id)
        available = True
        await self.adapter._messages()
        self.assertEqual(self.adapter._inbox_id, "real-inbox")

    async def test_incremental_cursor_persists_arrivals_before_advancing(self):
        calls = []

        def call(methods):
            method, args, tag = methods[0]
            calls.append((method, args))
            if method == "Email/query":
                self.assertEqual(args["filter"]["inMailbox"], "inbox-fixture")
                ids = [str(n) for n in range(args["position"], min(51, args["position"] + 50))]
                result = {"ids": ids, "queryState": "initial"}
            elif method == "Email/get":
                result = {"list": [{"id": key} for key in args["ids"]]}
            else:
                self.assertEqual(args["sinceQueryState"], "initial")
                result = {"added": [{"id": "51", "index": 51}], "newQueryState": "next"}
            return {"methodResponses": [[method, result, tag]]}

        self.adapter._client = types.SimpleNamespace(account_id="fixture", call=call)
        await self.adapter._messages()
        await self.adapter._messages()
        self.assertTrue(self.adapter._state.cursor()["complete"])
        self.assertEqual(self.adapter._state.get("50")[0], "queued")
        await self.adapter._messages()
        self.assertEqual(self.adapter._state.cursor()["state"], "next")
        self.assertEqual(self.adapter._state.get("51")[0], "queued")
        self.assertEqual(
            [m for m, _ in calls],
            [
                "Email/query",
                "Email/get",
                "Email/query",
                "Email/get",
                "Email/queryChanges",
                "Email/get",
            ],
        )

    async def test_status_refresh_updates_owner_address_and_authserv(self):
        updated = {
            **self.adapter._channel,
            "status": "ready",
            "address": "renamed@example.test",
            "authserv_id": "other-mx.example.test",
        }
        with (
            patch.object(channel.time, "monotonic", return_value=0),
            patch.object(owner, "request", return_value=updated) as request,
        ):
            await self.adapter._refresh_status()
            await self.adapter._refresh_status()
        request.assert_called_once()
        self.assertEqual(self.adapter._channel["address"], "renamed@example.test")
        self.assertEqual(self.adapter._authserv_id, "other-mx.example.test")
        self.adapter._status_checked = None
        with (
            patch.object(owner, "request", return_value={**updated, "authserv_id": ""}),
            self.assertRaisesRegex(ValueError, "authserv_id_missing"),
        ):
            await self.adapter._refresh_status()
        self.assertEqual(self.adapter._authserv_id, "other-mx.example.test")

    async def test_processing_payload_and_cursor_survive_restart(self):
        self.adapter._state.put(
            "inbound",
            "processing",
            {"metadata": {"subject": "Hi"}, "text": "Hello", "internal": False, "skill": None},
        )
        self.adapter._state.ingest([], {"complete": True, "state": "cursor-token"})
        other = InboxState(Path(self.temp.name) / "state.sqlite3")
        try:
            self.assertEqual(json.loads(other.get("inbound")[2])["metadata"]["subject"], "Hi")
            self.assertEqual(other.cursor()["state"], "cursor-token")
        finally:
            other.close()
