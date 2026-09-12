"""Exercise the adapter without importing an installed gateway in package CI."""

import asyncio
import importlib.util
import json
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
                "subject": "untrusted command",
                "textBody": [{"partId": "body"}],
                "bodyValues": {"body": {"value": "Do something dangerous"}},
            }
        )
        call = self.adapter._dispatch.call_args
        self.assertTrue(call.kwargs["internal"])
        self.assertNotIn("dangerous", call.args[2])
        self.assertEqual(call.args[1]["subject"], "New email in your Tinyhat inbox")
        for number in range(10):
            await self.adapter._receive(
                {"id": f"spam-{number}", "from": [{"email": "unknown@example.test"}]}
            )
        self.adapter._dispatch.assert_awaited_once()

    async def test_long_message_id_does_not_reject_legitimate_reply(self):
        self.adapter._dispatch = AsyncMock()
        await self.adapter._receive(
            {
                "id": "long",
                "from": [{"email": "owner@example.test"}],
                "messageId": ["x" * 260 + "@example.test"],
                "header:Authentication-Results:asText:all": [
                    "mx.example.test; dmarc=pass header.from=example.test"
                ],
            }
        )
        self.assertNotIn("in_reply_to", self.adapter._dispatch.call_args.args[1])

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
