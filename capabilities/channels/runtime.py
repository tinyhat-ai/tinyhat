"""Public runtime adapter for encrypted channel installation.

The platform owns assignment and credentials; this adapter validates the local
provider configuration using documented Hermes interfaces. No model settings
or user files are replaced.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..secrets.handoff import (
    _decrypt_ciphertext,
    _generate_key_pair,
    _hermes_env_path,
    _read_env_value,
    _set_hermes_secret,
)
from ..slack.connection import (
    _app_id_from_app_token,
    _generate_hermes_slack_manifest,
    _open_slack_home_channel,
    _parse_connection_bundle,
    _slack_api_call,
    _validate_slack_credentials,
)

MAX_ASSIGNMENT_LENGTH = 160
MAX_BUNDLE_BYTES = 8192
MAX_CIPHER_CHUNKS = 44
MAX_ENCODED_CHUNK_BYTES = 1024
CHANNEL_KEYS = {
    "telegram": (
        "TELEGRAM_ALLOWED_USERS",
        "TELEGRAM_HOME_CHANNEL",
        "TELEGRAM_HOME_CHANNEL_NAME",
        "TINYHAT_SETTINGS_MINIAPP_URL",
        "TELEGRAM_BOT_TOKEN",
    ),
    "slack": (
        "SLACK_ALLOWED_USERS",
        "SLACK_HOME_CHANNEL",
        "SLACK_HOME_CHANNEL_NAME",
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
    ),
}


def _atomic_private_write(path: Path, value: str, *, exclusive=False):
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as target:
            target.write(value)
            target.flush()
            os.fsync(target.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _directory(assignment: str) -> Path:
    if not assignment or len(assignment) > MAX_ASSIGNMENT_LENGTH:
        raise ValueError("A current Computer assignment is required.")
    root = (
        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        / "tinyhat"
        / "channels"
    )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    directory = root / hashlib.sha256(assignment.encode()).hexdigest()
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory


def prepare_key(assignment: str) -> dict[str, str]:
    directory = _directory(assignment)
    private_path, public_path = directory / "private.pem", directory / "public.pem"
    if private_path.exists() and not public_path.exists():
        result = subprocess.run(
            ["openssl", "pkey", "-in", str(private_path), "-pubout"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            _atomic_private_write(public_path, result.stdout)
        else:
            # No public key has been returned, so no credentials can be bound
            # to a partial write. Never rotate a key with a published public half.
            private_path.unlink()
    if not private_path.exists():
        if public_path.exists():
            raise ValueError("The published channel key needs recovery.")
        private, public = _generate_key_pair()
        # Exclusive create prevents replacing the only key able to decrypt a
        # previously submitted bundle. Runtime commands serialize this adapter.
        _atomic_private_write(private_path, private, exclusive=True)
        _atomic_private_write(public_path, public)
    public = public_path.read_text(encoding="utf-8")
    return {
        "public_key_pem": public,
        "key_fingerprint": hashlib.sha256(public.encode()).hexdigest(),
    }


def applied_revision(assignment: str, provider: str) -> str | None:
    if provider not in {"telegram", "slack"}:
        raise ValueError("Unknown channel.")
    path = _directory(assignment) / f"{provider}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text()).get("revision")


def record_applied(assignment: str, provider: str, revision: str) -> None:
    if provider not in {"telegram", "slack"}:
        raise ValueError("Unknown channel.")
    path = _directory(assignment) / f"{provider}.json"
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as target:
        json.dump({"revision": revision}, target)
    temporary.replace(path)


def install_channel(assignment: str, channel: dict) -> dict:
    provider = channel.get("provider")
    if provider == "telegram":
        token, owner = str(channel.get("bot_token") or ""), str(channel.get("owner_id") or "")
        if (
            not re.fullmatch(r"[1-9][0-9]*:[A-Za-z0-9_-]{20,}", token)
            or not owner.isdigit()
            or int(owner) <= 0
        ):
            raise ValueError("Telegram credentials or owner are invalid.")
        values = {
            "TELEGRAM_ALLOWED_USERS": owner,
            "TELEGRAM_HOME_CHANNEL": owner,
            "TELEGRAM_HOME_CHANNEL_NAME": "Owner DM",
            "TINYHAT_SETTINGS_MINIAPP_URL": str(channel.get("settings_miniapp_url") or ""),
            "TELEGRAM_BOT_TOKEN": token,
        }
        for name, value in values.items():
            _set_hermes_secret(name, value)
        return {"provider": provider}
    if provider != "slack":
        raise ValueError("Unknown channel.")
    key = prepare_key(assignment)
    if channel.get("key_fingerprint") != key["key_fingerprint"]:
        raise ValueError("Slack credentials belong to another Computer key.")
    private = (_directory(assignment) / "private.pem").read_text(encoding="utf-8")
    envelope = channel.get("ciphertext")
    chunks = envelope.get("ciphertext_chunks_b64") if isinstance(envelope, dict) else None
    if (
        not isinstance(chunks, list)
        or not 1 <= len(chunks) <= MAX_CIPHER_CHUNKS
        or any(
            not isinstance(chunk, str) or len(chunk) > MAX_ENCODED_CHUNK_BYTES for chunk in chunks
        )
    ):
        raise ValueError("Invalid channel credential envelope.")
    plaintext = ""
    try:
        plaintext = _decrypt_ciphertext(private, envelope)
        if len(plaintext.encode()) > MAX_BUNDLE_BYTES:
            raise ValueError("Channel credentials are too large.")
        bundle = _parse_connection_bundle(plaintext)
    finally:
        plaintext = ""
    try:
        metadata = _validate_slack_credentials(bundle)
        # auth.test can omit app_id. bots.info binds the bot token to the app
        # identity embedded in the Socket Mode token before any local write.
        auth = _slack_api_call("auth.test", token=bundle["bot_token"], stage="bot_auth")
        bot = (
            _slack_api_call(
                "bots.info",
                token=bundle["bot_token"],
                params={"bot": auth["bot_id"]},
                stage="app_identity",
            ).get("bot")
            or {}
        )
        if not bot.get("app_id") or bot["app_id"] != _app_id_from_app_token(bundle["app_token"]):
            raise ValueError("Slack tokens must belong to the same agent.")
        home = _open_slack_home_channel(bundle)
        for name, value in (
            ("SLACK_ALLOWED_USERS", bundle["allowed_users"]),
            ("SLACK_HOME_CHANNEL", home),
            ("SLACK_HOME_CHANNEL_NAME", "Owner DM"),
            ("SLACK_BOT_TOKEN", bundle["bot_token"]),
            ("SLACK_APP_TOKEN", bundle["app_token"]),
        ):
            _set_hermes_secret(name, value)
        return {"provider": provider, **metadata}
    finally:
        bundle.clear()


def slack_manifest() -> dict:
    return _generate_hermes_slack_manifest()


def snapshot_channel(provider: str) -> dict[str, str | None]:
    """Keep only this provider's previous values in memory for activation recovery."""
    path = _hermes_env_path(shutil.which("hermes") or "hermes")
    return {name: _read_env_value(path, name) for name in CHANNEL_KEYS[provider]}


def restore_channel(snapshot: dict[str, str | None]) -> None:
    """Restore a failed activation; empty values disable newly added providers."""
    for name, value in snapshot.items():
        if name not in {key for keys in CHANNEL_KEYS.values() for key in keys}:
            raise ValueError("Invalid channel recovery key.")
        _set_hermes_secret(name, value or "")
