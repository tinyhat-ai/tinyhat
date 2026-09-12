"""Durable inbox state and verification independent of the gateway SDK."""

import hashlib
import json
import os
import re
import sqlite3
import time


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def authenticated_owner(message, owner_email, authserv_id):
    """Only the receiving MTA's first authentication result can authorize From."""
    senders = message.get("from") or []
    if len(senders) != 1 or senders[0].get("email", "").lower() != owner_email.lower():
        return False
    values = message.get("header:Authentication-Results:asText:all") or []
    if not values or not isinstance(values[0], str):
        return False
    result = values[0].lower()
    if result.split(";", 1)[0].strip() != authserv_id.lower():
        return False
    domain = owner_email.rsplit("@", 1)[1].lower()
    return any(
        re.search(r"\bdmarc\s*=\s*pass\b", part)
        and re.search(r"\bheader\.from\s*=\s*" + re.escape(domain) + r"(?:\s|;|$)", part)
        for part in result.split(";")
    )


class InboxState:
    def __init__(self, path):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, state TEXT NOT NULL, updated REAL NOT NULL, payload TEXT)"
        )
        self.db.commit()

    def get(self, key):
        return self.db.execute(
            "SELECT state, updated, payload FROM messages WHERE id=?", (key,)
        ).fetchone()

    def put(self, key, state, payload=None):
        self.db.execute(
            "INSERT INTO messages VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state, updated=excluded.updated, payload=excluded.payload",
            (key, state, time.time(), json.dumps(payload) if payload is not None else None),
        )
        self.db.commit()

    def pending(self):
        return self.db.execute(
            "SELECT id, state, updated, payload FROM messages WHERE state='outbox' ORDER BY updated LIMIT 20"
        ).fetchall()

    def close(self):
        self.db.close()
