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
    """Only the receiving MTA's first authentication result can authorize From.

    Requires the managed receiving MTA to verify DMARC and prepend its own
    Authentication-Results on every delivery. A public authserv-id alone does
    not authenticate a header supplied by the sender.
    """
    senders = message.get("from") or []
    if len(senders) != 1 or senders[0].get("email", "").lower() != owner_email.lower():
        return False
    values = message.get("header:Authentication-Results:asText:all") or []
    if not values or not isinstance(values[0], str):
        return False
    result = values[0].lower()
    server = result.split(";", 1)[0].strip()
    if re.sub(r"\s+\d+$", "", server) != authserv_id.lower():
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
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS cursor (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(messages)")}
        for name, definition in (
            ("attempts", "INTEGER NOT NULL DEFAULT 0"),
            ("error", "TEXT"),
            ("retry_at", "REAL NOT NULL DEFAULT 0"),
        ):
            if name not in columns:
                self.db.execute(f"ALTER TABLE messages ADD COLUMN {name} {definition}")
        self.db.commit()

    def get(self, key):
        return self.db.execute(
            "SELECT state, updated, payload FROM messages WHERE id=?", (key,)
        ).fetchone()

    def put(self, key, state, payload=None):
        self.db.execute(
            "INSERT INTO messages (id,state,updated,payload) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state, updated=excluded.updated, payload=excluded.payload",
            (key, state, time.time(), json.dumps(payload) if payload is not None else None),
        )
        self.db.commit()

    def pending(self):
        return self.db.execute(
            "SELECT id, state, updated, payload FROM messages WHERE state='outbox' AND retry_at<=? ORDER BY updated LIMIT 20",
            (time.time(),),
        ).fetchall()

    def cursor(self):
        row = self.db.execute("SELECT value FROM cursor WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {}

    def uncertain(self):
        return self.db.execute(
            "SELECT id,payload FROM messages WHERE state='uncertain' AND retry_at<=? ORDER BY retry_at LIMIT 20",
            (time.time(),),
        ).fetchall()

    def defer_lookup(self, key):
        self.db.execute("UPDATE messages SET retry_at=? WHERE id=?", (time.time() + 3600, key))
        self.db.commit()

    def ingest(self, messages, cursor):
        with self.db:
            for message in messages:
                self.db.execute(
                    "INSERT OR IGNORE INTO messages (id,state,updated,payload) VALUES (?,'queued',?,?)",
                    (message["id"], time.time(), json.dumps(message)),
                )
            self.db.execute("INSERT OR REPLACE INTO cursor VALUES (1,?)", (json.dumps(cursor),))

    def arrivals(self, retry_seconds):
        return self.db.execute(
            "SELECT id,state,payload FROM messages WHERE state='queued' OR (state='processing' AND updated<?) ORDER BY updated LIMIT 50",
            (time.time() - retry_seconds,),
        ).fetchall()

    def delivery_attempt(self, key, error, delay, limit, *, terminal=False):
        attempts = (
            self.db.execute("SELECT attempts FROM messages WHERE id=?", (key,)).fetchone()[0] + 1
        )
        failed = terminal or attempts >= limit
        with self.db:
            self.db.execute(
                "UPDATE messages SET attempts=?,error=?,state=?,retry_at=?,updated=? WHERE id=?",
                (
                    attempts,
                    error,
                    "failed" if failed else "outbox",
                    time.time() + max(delay, min(3600, 30 * 2**attempts)),
                    time.time(),
                    key,
                ),
            )
        return failed

    def close(self):
        self.db.close()
