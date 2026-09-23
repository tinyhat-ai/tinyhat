"""Receive Stripe Projects credentials only on the assigned Computer."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _private_directory() -> Path:
    home = Path.home()
    directory = home / ".config" / "tinyhat" / "stripe-projects"
    for part in (home / ".config", home / ".config" / "tinyhat", directory):
        if part.is_symlink():
            raise ValueError("The private credential directory cannot be a link.")
        part.mkdir(mode=0o700, exist_ok=True)
        if not stat.S_ISDIR(part.stat().st_mode):
            raise ValueError("The private credential path must be a directory.")
    if any((part / ".git").exists() for part in (directory, *directory.parents)):
        raise ValueError("The credential directory must be outside Git.")
    directory.chmod(0o700)
    return directory


def _decrypt(envelope: dict[str, Any], project_id: str, private_key) -> dict:
    public_key = private_key.public_key()
    digest = hashlib.sha256(
        public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).hexdigest()
    aad = f"tinyhat-stripe-project-v1:{project_id}:{digest}"
    if (
        envelope.get("algorithm") != "RSA-OAEP-256+A256GCM"
        or envelope.get("key_fingerprint") != digest
        or envelope.get("aad") != aad
    ):
        raise ValueError("Stripe credential envelope does not match this Computer.")
    try:
        wrapped = base64.b64decode(envelope["wrapped_key"], validate=True)
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        symmetric_key = private_key.decrypt(
            wrapped,
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        values = json.loads(AESGCM(symmetric_key).decrypt(nonce, ciphertext, aad.encode()))
        data = json.loads(values["stripe_environment_info"])
    except (KeyError, ValueError, TypeError, binascii.Error, InvalidTag):
        raise ValueError("Tinyhat returned an invalid credential envelope.") from None
    if not isinstance(data, dict) or not isinstance(
        data.get("resource_access_configurations"), list
    ):
        raise ValueError("Stripe did not return usable Project credentials.")
    return data


def sync_environment(client, base: str) -> dict:
    """Keep revealed credentials out of platform responses, chat, and Git."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    result = client.post_json(base + "/environment-info", {"public_key_pem": public_key_pem})
    project_id = result.get("project_id")
    envelope = result.get("envelope")
    if not isinstance(project_id, str) or not isinstance(envelope, dict):
        raise ValueError("Tinyhat returned an invalid credential envelope.")
    data = _decrypt(envelope, project_id, private_key)
    directory = _private_directory()
    destination = directory / (hashlib.sha256(project_id.encode()).hexdigest() + ".json")
    if destination.is_symlink():
        raise ValueError("The private credential file cannot be a link.")
    descriptor, temp_name = tempfile.mkstemp(prefix=".stripe-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, destination)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return {
        "project_id": project_id,
        "resource_count": len(data["resource_access_configurations"]),
        "credential_file": str(destination),
    }
