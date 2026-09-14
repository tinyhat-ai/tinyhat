"""Owner-requested channel setup from the assigned Computer."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from ...platform import PlatformError, build_platform_client, computer_api_path
from ...tool_errors import tool_error_json
from ..secrets.handoff import SecretHandoffError
from ..slack.connection import _parse_connection_bundle

TOOL = "tinyhat_channels"
MAX_BUNDLE_BYTES = 8192
SAFE_CHANNEL_ERRORS = {
    "owner_unavailable",
    "setup_failed",
    "invalid_credentials",
    "gateway_unavailable",
    "readiness_unknown",
    "settings_unavailable",
    "network_unavailable",
}


class ChannelInputError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.public_message = code, message
        super().__init__(message)


def pairing_result(payload):
    try:
        url, qr = urlsplit(payload["url"]), urlsplit(payload["qr_url"])
        token = url.path.rsplit("/", 1)[-1]
        for link in (url, qr):
            if (
                (
                    link.scheme != "https"
                    and not (
                        link.scheme == "http" and link.hostname in {"localhost", "127.0.0.1", "::1"}
                    )
                )
                or link.username
                or link.password
                or link.query
                or link.fragment
            ):
                raise ValueError()
        if (
            not re.fullmatch(r"/tinyhat/connect/telegram/thch_[A-Za-z0-9_-]{43}", url.path)
            or (url.scheme, url.netloc) != (qr.scheme, qr.netloc)
            or qr.path != f"/hapi/v2/channel-links/telegram/{token}/qr"
        ):
            raise ValueError()
        return {
            key: payload.get(key)
            for key in ["url", "qr_url", "expires_at", "bot_name", "bot_username"]
        }
    except (KeyError, ValueError, TypeError):
        raise ChannelInputError(
            "invalid_pairing_link",
            "Tinyhat returned an invalid pairing link. Request a fresh link.",
        ) from None


def encrypt_bundle(public_key: str, bundle: dict) -> dict:
    if not shutil.which("openssl"):
        raise ChannelInputError(
            "encryption_unavailable",
            "OpenSSL is required to encrypt the credentials on this Computer.",
        )
    plaintext = json.dumps(bundle).encode()
    if len(plaintext) > MAX_BUNDLE_BYTES:
        raise ValueError("Credentials file is too large.")
    chunks = []
    with tempfile.TemporaryDirectory(prefix="tinyhat-channel-") as directory:
        key = Path(directory) / "public.pem"
        key.write_text(public_key, encoding="utf-8")
        for offset in range(0, len(plaintext), 190):
            result = subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-encrypt",
                    "-pubin",
                    "-inkey",
                    str(key),
                    "-pkeyopt",
                    "rsa_padding_mode:oaep",
                    "-pkeyopt",
                    "rsa_oaep_md:sha256",
                ],
                input=plaintext[offset : offset + 190],
                capture_output=True,
                check=True,
                timeout=10,
            )
            chunks.append(base64.b64encode(result.stdout).decode())
    return {
        "schema": "tinyhat_private_secret_ciphertext_v1",
        "algorithm": "RSA-OAEP-256",
        "encoding": "base64",
        "chunk_size": 190,
        "ciphertext_chunks_b64": chunks,
    }


def _credentials_file(value: object) -> dict:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError("Use an absolute credentials-file path.")
    path = Path(value)
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_mode & 0o077
        or info.st_uid != os.getuid()
        or info.st_size > MAX_BUNDLE_BYTES
    ):
        raise ValueError(
            "Use a private file owned by the current user, with mode 600 and at most 8 KB."
        )
    # Parsing enforces both tokens and the owner's allowlist without echoing values.
    bundle = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(bundle, dict) or set(bundle) - {
        "schema",
        "bot_token",
        "app_token",
        "allowed_users",
    }:
        raise ValueError("Invalid credentials file.")
    bundle.setdefault("schema", "tinyhat_slack_connection_bundle_v1")
    return _parse_connection_bundle(json.dumps(bundle))


def _public_status(payload: dict) -> dict:
    return {
        "channels": [
            {
                "provider": row["provider"],
                "status": row["status"],
                "name": row.get("name"),
                "error": row.get("error")
                if row.get("error") in SAFE_CHANNEL_ERRORS
                else "setup_failed"
                if row.get("error")
                else None,
            }
            for row in payload.get("channels", [])
            if row.get("provider") in {"email", "slack", "telegram"}
        ],
        "slack_ready": bool(payload.get("public_key_pem")),
        "slack_manifest": payload.get("slack_manifest"),
    }


def channels(args: dict | None = None, **_) -> str:
    args = args or {}
    action = args.get("action", "status")
    try:
        if action not in {"status", "prepare", "telegram_link", "slack_connect"}:
            raise ValueError("Unknown channel operation.")
        allowed = {"action", "bot_name", "bot_username", "credentials_file"}
        if set(args) - allowed:
            raise ValueError("Unexpected fields. Credentials must be provided in a private file.")
        client, authentication = build_platform_client()
        base = computer_api_path(authentication, "channels", version="v2")
        if action == "status":
            result = _public_status(client.get_json(base + "/status"))
        elif action == "prepare":
            result = client.post_json(base + "/prepare", {})
        elif action == "telegram_link":
            body = {key: args[key] for key in ["bot_name", "bot_username"] if key in args}
            result = client.post_json(base + "/telegram/link", body)
            result = pairing_result(result)
        else:
            status = client.get_json(base + "/status")
            public_key, fingerprint = status.get("public_key_pem"), status.get("key_fingerprint")
            if not public_key or hashlib.sha256(public_key.encode()).hexdigest() != fingerprint:
                raise ChannelInputError(
                    "computer_not_prepared",
                    "Prepare the Computer first, then retry once its key is ready.",
                )
            try:
                bundle = _credentials_file(args.get("credentials_file"))
            except (ValueError, OSError, SecretHandoffError):
                raise ChannelInputError(
                    "credentials_file_invalid",
                    "Use an absolute path to a private, owned file (mode 600, at most 8 KB) containing both Slack tokens and your member ID.",
                ) from None
            try:
                bundle["schema"] = "tinyhat_slack_connection_bundle_v1"
                encrypted = encrypt_bundle(public_key, bundle)
            finally:
                bundle.clear()
            result = client.post_json(
                base + "/slack", {"key_fingerprint": fingerprint, "ciphertext": encrypted}
            )
        return json.dumps(result)
    except ChannelInputError as exc:
        return tool_error_json(tool=TOOL, error_name=exc.code, message=exc.public_message)
    except PlatformError as exc:
        invalid = exc.status_code in {400, 422}
        return tool_error_json(
            tool=TOOL,
            error_name="invalid_channel_request" if invalid else "platform_unavailable",
            message="Check the supplied channel fields and bot username."
            if invalid
            else "Tinyhat could not complete the request. Check channel status before retrying.",
        )
    except (
        SecretHandoffError,
        ValueError,
        TypeError,
        KeyError,
        OSError,
        subprocess.SubprocessError,
    ):
        return tool_error_json(
            tool=TOOL,
            error_name="channel_setup_unavailable",
            message="Could not complete channel setup. Check status before retrying. For Slack, prepare the Computer and use a private credentials file with both tokens and your member ID.",
        )
