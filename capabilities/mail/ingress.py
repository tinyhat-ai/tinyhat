"""SDK-independent owner email ingress shared with native coding sessions.

The Hermes inbox ledger remains the source of consumed message IDs. A native
receiver marks an arrival done only after its own durable inbox commits it.
"""

import json
import logging
import os
from pathlib import Path

from . import owner
from .channel_state import InboxState, _hash, authentication_failure, automatic_message, utc_date
from .tool import _discover_session, _mailbox_id_by_role, _method_result, _plain_text_body

PAGE_SIZE = 50
logger = logging.getLogger(__name__)


class OwnerInbox:
    def __init__(self):
        self.channel = owner.request("status")
        if self.channel.get("status") != "ready" or not self.channel.get("authserv_id"):
            raise ValueError("Owner inbox is not ready.")
        self.client, _ = _discover_session()
        root = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
        self.state = InboxState(
            root / "tinyhat/email" / (_hash(self.channel["agent_id"]) + ".sqlite3")
        )
        self.inbox = _mailbox_id_by_role(self.client, "inbox")

    def poll(self, accept):
        # Revalidate assignment/owner on every poll; a mailbox rename preserves
        # the agent-keyed ledger. Provider messages never supply owner identity.
        channel = owner.request("status")
        if channel.get("status") != "ready" or channel.get("agent_id") != self.channel["agent_id"]:
            raise ValueError("Owner inbox assignment changed.")
        self.channel = channel
        cursor = self.state.cursor()
        incremental = bool(cursor.get("complete"))
        method = "Email/queryChanges" if incremental else "Email/query"
        query = {
            "accountId": self.client.account_id,
            "filter": {
                "after": utc_date(os.environ["TINYHAT_EMAIL_CHANNEL_CREATED_AT"]),
                "inMailbox": self.inbox,
            },
            "sort": [{"property": "receivedAt", "isAscending": True}],
        }
        query.update(
            {"sinceQueryState": cursor["state"], "maxChanges": PAGE_SIZE}
            if incremental
            else {"position": cursor.get("position", 0), "limit": PAGE_SIZE}
        )
        response = self.client.call([[method, query, "q"]])
        if incremental and any(
            row[0] == "error" and row[1].get("type") in {"cannotCalculateChanges", "tooManyChanges"}
            for row in response.get("methodResponses", [])
        ):
            self.state.ingest([], {})
            return
        result = _method_result(response, method, "q")
        ids = (
            [item["id"] for item in result.get("added", [])]
            if incremental
            else result.get("ids", [])
        )
        next_cursor = (
            {"complete": True, "state": result["newQueryState"]}
            if incremental
            else {
                "state": cursor.get("state", result["queryState"]),
                "position": cursor.get("position", 0) + len(ids),
                "complete": len(ids) < PAGE_SIZE,
            }
        )
        ids = [key for key in ids if self.state.get(key) is None]
        messages = []
        if ids:
            response = self.client.call(
                [
                    [
                        "Email/get",
                        {
                            "accountId": self.client.account_id,
                            "ids": ids,
                            "properties": [
                                "id",
                                "from",
                                "header:From:all",
                                "subject",
                                "messageId",
                                "inReplyTo",
                                "references",
                                "receivedAt",
                                "textBody",
                                "htmlBody",
                                "bodyValues",
                                "header:Authentication-Results:all",
                                "header:Auto-Submitted:asText",
                            ],
                            "fetchTextBodyValues": True,
                            "fetchHTMLBodyValues": True,
                            "maxBodyValueBytes": 100000,
                        },
                        "g",
                    ]
                ]
            )
            messages = _method_result(response, "Email/get", "g").get("list", [])
        self.state.ingest(messages, next_cursor)
        for key, state, raw in self.state.arrivals(600):
            if key == "onboarding-welcome":
                continue  # Welcome/outbox delivery remains the Hermes adapter's job.
            if state == "processing":
                # A Hermes turn may already have performed external actions. Never
                # silently replay it through a different framework after switching.
                self.state.native_handoff_failed(key, "framework_switch_interrupted_turn", limit=0)
                logger.warning("Tinyhat email turn stopped (framework_switch_interrupted_turn)")
                continue
            try:
                message = json.loads(raw)
                if authentication_failure(
                    message, channel["owner_email"], channel["authserv_id"]
                ) is not None or automatic_message(message):
                    self.state.put(key, "done")
                    continue
                accept(
                    "email:" + key,
                    {
                        "provider": "email",
                        "conversation": "owner",
                        "sender": channel["owner_email"],
                        "message_id": key,
                        "subject": message.get("subject", ""),
                        "email_message_ids": message.get("messageId", []),
                        "text": _plain_text_body(message)[:20000],
                        "received_at": message.get("receivedAt"),
                        "reply_to": message.get("inReplyTo", []),
                        "references": message.get("references", []),
                    },
                )
                self.state.put(key, "done")
            except BufferError:
                # Runtime inbox capacity is backpressure, not a poison message.
                self.state.defer_native_handoff(key)
            except Exception:
                # An individual failed handoff must not starve later arrivals.
                # The native inbox deduplicates retries by the stable email key.
                failed = self.state.native_handoff_failed(key, "native_handoff_failed")
                logger.warning("Tinyhat email handoff %s", "failed" if failed else "will retry")

    def close(self):
        self.state.close()
