"""Durable inbox state and verification independent of the gateway SDK."""

import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone

MAX_AUTH_HEADER_BYTES = 16_384
FIRST_PRINTABLE_ASCII = 32


def utc_date(value):
    """Normalize platform timestamps to the JMAP UTCDate wire format."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    ).isoformat().replace("+00:00", "Z")


def automatic_message(message):
    return (message.get("header:Auto-Submitted:asText") or "").lower() not in {"", "no"}


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _auth_clauses(value):
    """Split machine-generated results without interpreting quoted claims.

    Semicolons inside a quoted property or nested comment are data, not a
    second authentication method. Reject malformed or oversized headers.
    """
    if not isinstance(value, str) or len(value) > MAX_AUTH_HEADER_BYTES:
        return []
    clauses, start, depth, quoted, escaped = [], 0, 0, False, False
    for index, char in enumerate(value):
        if ord(char) < FIRST_PRINTABLE_ASCII and char not in "\r\n\t":
            return []
        if escaped:
            escaped = False
        elif char == "\\" and (quoted or depth):
            escaped = True
        elif char == '"' and not depth:
            quoted = not quoted
        elif not quoted:
            if char == "(":
                depth += 1
            elif char == ")":
                if not depth:
                    return []
                depth -= 1
            elif char == ";" and not depth:
                clauses.append(value[start:index].strip())
                start = index + 1
    if depth or quoted or escaped:
        return []
    clauses.append(value[start:].strip())
    return clauses


def authentication_failure(message, owner_email, authserv_id):
    """Return a fixed rejection reason, or None for authenticated owner mail.

    The MTA MUST strip all incoming Authentication-Results, verify mail, and
    insert exactly one result on every SMTP delivery (including submission).
    Its configured hostname alone is not proof. Mailbox imports are not an
    authenticated ingress path; mailbox credentials are a trusted boundary.
    """
    if not isinstance(owner_email, str) or "@" not in owner_email or not authserv_id:
        return "invalid_owner_configuration"
    senders = message.get("from") or []
    from_headers = message.get("header:From:all")
    if (
        not isinstance(senders, list)
        or len(senders) != 1
        or not isinstance(senders[0], dict)
        or str(senders[0].get("email", "")).lower() != owner_email.lower()
        or not isinstance(from_headers, list)
        or len(from_headers) != 1
    ):
        return "owner_from_mismatch_or_ambiguity"
    return _result_failure(
        message.get("header:Authentication-Results:all") or [],
        authserv_id,
        owner_email.rsplit("@", 1)[1].lower(),
    )


def _result_failure(values, authserv_id, domain):
    if not isinstance(values, list) or len(values) != 1:
        return "missing_or_ambiguous_authentication_results"
    clauses = _auth_clauses(values[0])
    if not clauses[1:]:
        return "malformed_authentication_results"
    if not re.fullmatch(re.escape(authserv_id) + r"(?:\s+1)?", clauses[0], re.I | re.A):
        return "authserv_mismatch"
    dmarc = [part for part in clauses[1:] if re.match(r"dmarc\b", part, re.I | re.A)]
    # Deliberately accept the receiving Stalwart formatter's pass grammar,
    # not a search for pass inside reason text, comments or unknown properties.
    # Stalwart 0.16.15 / mail-auth 0.11.3 emits DMARC last. Fail closed if
    # that formatter contract changes, rather than swallowing a later claim.
    if len(dmarc) != 1 or dmarc != clauses[-1:]:
        return "missing_ambiguous_or_nonfinal_dmarc"
    if not (
        re.fullmatch(
            r"dmarc\s*=\s*pass\s+header\.from\s*=\s*(?:"
            + re.escape(domain)
            + r'|"'
            + re.escape(domain)
            + r'")'
            + r"(?:\s+policy\.dmarc=(?:none|quarantine|reject))?",
            dmarc[0],
            re.I | re.A,
        )
    ):
        return "dmarc_not_pass"
    return None


def authenticated_owner(message, owner_email, authserv_id):
    return authentication_failure(message, owner_email, authserv_id) is None


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
            ("turn_attempts", "INTEGER NOT NULL DEFAULT 0"),
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

    def start_turn(self, key, payload, limit, notice):
        """Persist the model budget independently of SMTP retries.

        Quarantine and enqueue the fixed owner notice together, so a restart
        cannot lose the notice or reset the budget for a failing message.
        """
        with self.db:
            row = self.db.execute(
                "SELECT state,turn_attempts FROM messages WHERE id=?", (key,)
            ).fetchone()
            if row and row[0] not in {"queued", "processing"}:
                return False
            attempts = row[1] if row else 0
            now = time.time()
            if attempts >= limit:
                self.db.execute(
                    "UPDATE messages SET state='failed',error='email_model_attempts_exhausted',updated=? WHERE id=?",
                    (now, key),
                )
                self.db.execute(
                    "INSERT OR IGNORE INTO messages (id,state,updated,payload) VALUES (?,'outbox',?,?)",
                    ("turn-failure-" + _hash(key), now, json.dumps(notice)),
                )
                return False
            self.db.execute(
                "INSERT INTO messages (id,state,updated,payload,turn_attempts) VALUES (?,'processing',?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET state='processing',updated=excluded.updated,payload=excluded.payload,turn_attempts=excluded.turn_attempts",
                (key, now, json.dumps(payload), attempts + 1),
            )
        return True

    def native_handoff_failed(self, key, reason, *, limit=5):
        """Bound per-arrival retries without replaying a possibly executed turn."""
        with self.db:
            attempts = self.db.execute(
                "SELECT turn_attempts FROM messages WHERE id=?", (key,)
            ).fetchone()[0] + 1
            failed = attempts >= limit
            self.db.execute(
                "UPDATE messages SET turn_attempts=?,error=?,state=?,updated=? WHERE id=?",
                (attempts, reason, "failed" if failed else "queued", time.time(), key),
            )
        return failed

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
