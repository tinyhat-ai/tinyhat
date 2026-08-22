"""Computer-local keys and ciphertext envelopes for local app sharing."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

CONTENT_ENCRYPTION_PROTOCOL = "browser-computer-e2ee-v1"
KEY_AGREEMENT_ALGORITHM = "ECDH-P256-HKDF-SHA256"
CONTENT_CIPHER = "AES-256-GCM"
LINK_FINGERPRINT_PARAMETER = CONTENT_ENCRYPTION_PROTOCOL
MAX_CIPHERTEXT_BYTES = 12 * 1024 * 1024
MAX_KEY_FILE_BYTES = 16 * 1024
P256_COORDINATE_BYTES = 32
HKDF_SALT_BYTES = 32
AES_GCM_NONCE_BYTES = 12


class LocalAppCryptoError(RuntimeError):
    """A local key or encrypted envelope is invalid."""


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str, *, maximum_bytes: int) -> bytes:
    clean = str(value or "").strip()
    if not clean or len(clean) > maximum_bytes * 2:
        raise LocalAppCryptoError("Encrypted local app payload is invalid.")
    try:
        decoded = base64.urlsafe_b64decode(clean + "=" * (-len(clean) % 4))
    except (ValueError, TypeError) as exc:
        raise LocalAppCryptoError("Encrypted local app payload is invalid.") from exc
    if not decoded or len(decoded) > maximum_bytes:
        raise LocalAppCryptoError("Encrypted local app payload is invalid.")
    return decoded


def _public_jwk(public_key: ec.EllipticCurvePublicKey) -> dict[str, str]:
    numbers = public_key.public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url_encode(numbers.x.to_bytes(32, "big")),
        "y": _b64url_encode(numbers.y.to_bytes(32, "big")),
    }


def _public_key_from_jwk(payload: dict[str, Any]) -> ec.EllipticCurvePublicKey:
    if payload.get("kty") != "EC" or payload.get("crv") != "P-256":
        raise LocalAppCryptoError("Browser key agreement is invalid.")
    x = _b64url_decode(str(payload.get("x") or ""), maximum_bytes=P256_COORDINATE_BYTES)
    y = _b64url_decode(str(payload.get("y") or ""), maximum_bytes=P256_COORDINATE_BYTES)
    if len(x) != P256_COORDINATE_BYTES or len(y) != P256_COORDINATE_BYTES:
        raise LocalAppCryptoError("Browser key agreement is invalid.")
    try:
        return ec.EllipticCurvePublicNumbers(
            int.from_bytes(x, "big"),
            int.from_bytes(y, "big"),
            ec.SECP256R1(),
        ).public_key()
    except ValueError as exc:
        raise LocalAppCryptoError("Browser key agreement is invalid.") from exc


def _fingerprint(public_key: ec.EllipticCurvePublicKey) -> str:
    encoded = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return _b64url_encode(hashlib.sha256(encoded).digest())


def _private_key_pem(private_key: ec.EllipticCurvePrivateKey) -> str:
    return private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


def _load_private_key(value: str) -> ec.EllipticCurvePrivateKey:
    try:
        loaded = serialization.load_pem_private_key(value.encode("ascii"), password=None)
    except (ValueError, TypeError) as exc:
        raise LocalAppCryptoError("Local app session key is invalid.") from exc
    if not isinstance(loaded, ec.EllipticCurvePrivateKey) or not isinstance(
        loaded.curve, ec.SECP256R1
    ):
        raise LocalAppCryptoError("Local app session key is invalid.")
    return loaded


@dataclass(frozen=True)
class SessionKey:
    """One Computer-local private key bound to a platform session id."""

    session_id: str
    private_key: ec.EllipticCurvePrivateKey
    public_jwk: dict[str, str]
    fingerprint: str
    expires_at_epoch: float


class SessionKeyStore:
    """Mode-0600 key files; private material never leaves the Computer."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, session_id: str) -> Path:
        if not session_id.startswith("las_") or not session_id.replace("_", "").isalnum():
            raise LocalAppCryptoError("Local app session id is invalid.")
        return self.root / f"{session_id}.json"

    def create(self, *, session_id: str, expires_at_epoch: float) -> SessionKey:
        if expires_at_epoch <= time.time():
            raise LocalAppCryptoError("Local app session already expired.")
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()
        payload = {
            "protocol": CONTENT_ENCRYPTION_PROTOCOL,
            "session_id": session_id,
            "private_key_pem": _private_key_pem(private_key),
            "public_jwk": _public_jwk(public_key),
            "fingerprint": _fingerprint(public_key),
            "expires_at_epoch": expires_at_epoch,
        }
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{session_id}-",
            suffix=".tmp",
            dir=self.root,
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(payload, output, separators=(",", ":"), sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            destination = self._path(session_id)
            os.replace(temporary, destination)
            destination.chmod(0o600)
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()
        return self.load(session_id)

    def load(self, session_id: str) -> SessionKey:
        path = self._path(session_id)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise LocalAppCryptoError("Local app session key was not found.") from exc
        if len(raw) > MAX_KEY_FILE_BYTES:
            raise LocalAppCryptoError("Local app session key is invalid.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalAppCryptoError("Local app session key is invalid.") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("protocol") != CONTENT_ENCRYPTION_PROTOCOL
            or payload.get("session_id") != session_id
        ):
            raise LocalAppCryptoError("Local app session key is invalid.")
        try:
            expires_at_epoch = float(payload["expires_at_epoch"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LocalAppCryptoError("Local app session key is invalid.") from exc
        if expires_at_epoch <= time.time():
            self.delete(session_id)
            raise LocalAppCryptoError("Local app session key expired.")
        private_key = _load_private_key(str(payload.get("private_key_pem") or ""))
        public_key = private_key.public_key()
        public_jwk = _public_jwk(public_key)
        fingerprint = _fingerprint(public_key)
        if payload.get("public_jwk") != public_jwk or payload.get("fingerprint") != fingerprint:
            raise LocalAppCryptoError("Local app session key is invalid.")
        return SessionKey(
            session_id=session_id,
            private_key=private_key,
            public_jwk=public_jwk,
            fingerprint=fingerprint,
            expires_at_epoch=expires_at_epoch,
        )

    def delete(self, session_id: str) -> None:
        with suppress(FileNotFoundError):
            self._path(session_id).unlink()


def encrypted_link(link: str, fingerprint: str) -> str:
    """Bind a browser link to the Computer key without sending it over HTTP."""

    if not fingerprint or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for character in fingerprint
    ):
        raise LocalAppCryptoError("Local app key fingerprint is invalid.")
    return f"{link}#{LINK_FINGERPRINT_PARAMETER}={fingerprint}"


def derive_content_key(
    *,
    session_key: SessionKey,
    browser_public_jwk: dict[str, Any],
    salt: bytes,
) -> bytes:
    """Derive one connection key from an ephemeral browser ECDH key."""

    if len(salt) != HKDF_SALT_BYTES:
        raise LocalAppCryptoError("Browser key agreement is invalid.")
    peer = _public_key_from_jwk(browser_public_jwk)
    shared = session_key.private_key.exchange(ec.ECDH(), peer)
    info = (
        f"{CONTENT_ENCRYPTION_PROTOCOL}\0{session_key.session_id}\0{session_key.fingerprint}"
    ).encode("ascii")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=info,
    ).derive(shared)


def encrypt_json(*, key: bytes, payload: dict[str, Any], aad: bytes) -> dict[str, str]:
    nonce = os.urandom(AES_GCM_NONCE_BYTES)
    plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(plaintext) > MAX_CIPHERTEXT_BYTES:
        raise LocalAppCryptoError("Local app response is too large.")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    return {"nonce": _b64url_encode(nonce), "ciphertext": _b64url_encode(ciphertext)}


def decrypt_json(
    *,
    key: bytes,
    nonce: str,
    ciphertext: str,
    aad: bytes,
) -> dict[str, Any]:
    raw_nonce = _b64url_decode(nonce, maximum_bytes=AES_GCM_NONCE_BYTES)
    raw_ciphertext = _b64url_decode(ciphertext, maximum_bytes=MAX_CIPHERTEXT_BYTES)
    if len(raw_nonce) != AES_GCM_NONCE_BYTES:
        raise LocalAppCryptoError("Encrypted local app payload is invalid.")
    try:
        plaintext = AESGCM(key).decrypt(raw_nonce, raw_ciphertext, aad)
    except InvalidTag as exc:
        raise LocalAppCryptoError("Encrypted local app payload is invalid.") from exc
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalAppCryptoError("Encrypted local app payload is invalid.") from exc
    if not isinstance(payload, dict):
        raise LocalAppCryptoError("Encrypted local app payload is invalid.")
    return payload


def request_aad(*, session_id: str, connection_id: str, request_id: str) -> bytes:
    return f"{CONTENT_ENCRYPTION_PROTOCOL}\0request\0{session_id}\0{connection_id}\0{request_id}".encode(
        "ascii"
    )


def response_aad(*, session_id: str, connection_id: str, request_id: str) -> bytes:
    return f"{CONTENT_ENCRYPTION_PROTOCOL}\0response\0{session_id}\0{connection_id}\0{request_id}".encode(
        "ascii"
    )


__all__ = [
    "CONTENT_CIPHER",
    "CONTENT_ENCRYPTION_PROTOCOL",
    "KEY_AGREEMENT_ALGORITHM",
    "LINK_FINGERPRINT_PARAMETER",
    "LocalAppCryptoError",
    "SessionKey",
    "SessionKeyStore",
    "decrypt_json",
    "derive_content_key",
    "encrypt_json",
    "encrypted_link",
    "request_aad",
    "response_aad",
]
