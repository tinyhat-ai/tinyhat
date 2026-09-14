"""Public runtime adapter for encrypted channel installation.

The platform owns assignment and credentials; this adapter validates the local
provider configuration using documented Hermes interfaces. No model settings
or user files are replaced.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from ..secrets.handoff import _decrypt_ciphertext, _generate_key_pair, _set_hermes_secret
from ..slack.connection import (
    _app_id_from_app_token,
    _generate_hermes_slack_manifest,
    _open_slack_home_channel,
    _parse_connection_bundle,
    _slack_api_call,
    _validate_slack_credentials,
)

MAX_ASSIGNMENT_LENGTH = 160


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
    if not private_path.exists():
        private, public = _generate_key_pair()
        # Exclusive create prevents replacing the only key able to decrypt a
        # previously submitted bundle. Runtime commands serialize this adapter.
        fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as target:
            target.write(private)
        public_path.write_text(public, encoding="utf-8")
        public_path.chmod(0o600)
    if not public_path.exists():
        # Recover a crash after saving the private key; never rotate that key.
        result = subprocess.run(
            ["openssl", "pkey", "-in", str(private_path), "-pubout"],
            capture_output=True,
            text=True,
            check=True,
        )
        public_path.write_text(result.stdout, encoding="utf-8")
        public_path.chmod(0o600)
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
        if not token or not owner.isdigit() or int(owner) <= 0:
            raise ValueError("Telegram credentials or owner are invalid.")
        values = {
            "TELEGRAM_ALLOWED_USERS": owner,
            "TELEGRAM_HOME_CHANNEL": owner,
            "TELEGRAM_HOME_CHANNEL_NAME": "Owner DM",
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
    plaintext = _decrypt_ciphertext(private, channel["ciphertext"])
    bundle = _parse_connection_bundle(plaintext)
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
