"""Encrypted Computer-local secret storage for one-customer Hats.

Only the encrypted handoff worker calls ``set_hat_secret`` with plaintext.
Values are immediately re-encrypted with the Hat's stable local key pair
before the atomic store write. Every public return shape is value-blind:
names, counts, paths, and booleans.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

HAT_HANDLE_RE = re.compile(
    r"^(?P<account>[a-z0-9][a-z0-9_-]{0,46})/hats/" r"(?P<key>[a-z0-9][a-z0-9_-]{0,46})$"
)
SECRET_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,126}$")
KEY_ALGORITHM = "RSA-OAEP-256"
LEGACY_STORE_SCHEMA = "tinyhat_hat_secrets_v1"
STORE_SCHEMA = "tinyhat_hat_secrets_v2"
BUNDLE_SCHEMA = "tinyhat_hat_credentials_bundle_v1"
AUTHENTICATED_ENVELOPE_SCHEMA = "tinyhat_hat_credentials_envelope_v1"
CREATOR_SIGNATURE_ALGORITHM = "RSA-PSS-SHA256"
# A 2048-bit RSA key with SHA-256 OAEP can encrypt at most 190 bytes. The
# production key is 3072 bits, but this conservative size also keeps imported
# or test key pairs interoperable.
RSA_OAEP_CHUNK_BYTES = 160


class HatSecretStoreError(RuntimeError):
    """The Computer-local Hat secret store could not be read or changed."""


def _store_root() -> Path:
    configured = os.getenv("TINYHAT_HAT_STORE_DIR", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".tinyhat" / "hats"


def normalize_hat_handle(value: str) -> str:
    handle = str(value or "").strip().lower()
    if not HAT_HANDLE_RE.fullmatch(handle):
        raise HatSecretStoreError("Hat handle is invalid.")
    return handle


def normalize_secret_name(value: str) -> str:
    name = str(value or "").strip().upper()
    if not SECRET_NAME_RE.fullmatch(name):
        raise HatSecretStoreError("Use an env-style credential name such as EXA_API_KEY.")
    return name


def hat_secret_store_path(handle: str) -> Path:
    matched = HAT_HANDLE_RE.fullmatch(normalize_hat_handle(handle))
    if matched is None:  # pragma: no cover - guarded by normalize_hat_handle
        raise HatSecretStoreError("Hat handle is invalid.")
    return _store_root() / matched.group("account") / matched.group("key") / "secrets.json"


def ensure_hat_key_pair(
    handle: str,
    *,
    key_pair_factory: Callable[[], tuple[str, str]] | None = None,
) -> tuple[Path, str]:
    """Return the stable local key pair used by every credential in one Hat."""
    directory = hat_secret_store_path(handle).parent
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    private_path = directory / "credentials-private.pem"
    public_path = directory / "credentials-public.pem"
    lock_path = directory / "credentials-key.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock_path, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if private_path.exists() != public_path.exists():
            raise HatSecretStoreError("The local Hat credential key pair is incomplete.")
        if private_path.exists():
            private_path.chmod(0o600)
            public_path.chmod(0o600)
            return private_path, public_path.read_text(encoding="utf-8")

        factory = key_pair_factory or _generate_key_pair
        private_key_pem, public_key_pem = factory()
        _write_key_material(private_path, private_key_pem)
        _write_key_material(public_path, public_key_pem)
        return private_path, public_key_pem


@contextmanager
def _locked_store(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    lock_path = path.with_suffix(".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock_path, 0o600)
    try:
        with os.fdopen(descriptor, "r+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
    finally:
        # The lock file intentionally stays beside the store so concurrent
        # processes always lock the same inode.
        pass


def _read_store(path: Path, *, handle: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema": LEGACY_STORE_SCHEMA,
            "handle": handle,
            "secrets": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HatSecretStoreError("The local Hat secret store is unreadable.") from exc
    if not isinstance(payload, dict) or payload.get("handle") != handle:
        raise HatSecretStoreError("The local Hat secret store has an invalid format.")
    if payload.get("schema") == LEGACY_STORE_SCHEMA and isinstance(payload.get("secrets"), dict):
        return payload
    if (
        payload.get("schema") == STORE_SCHEMA
        and isinstance(payload.get("names"), list)
        and isinstance(payload.get("ciphertext_payload"), dict)
    ):
        return payload
    raise HatSecretStoreError("The local Hat secret store has an invalid format.")


def _store_values(
    path: Path,
    payload: dict[str, Any],
    *,
    handle: str,
) -> dict[str, str]:
    if payload.get("schema") == LEGACY_STORE_SCHEMA:
        return {
            normalize_secret_name(str(name)): str(value)
            for name, value in payload["secrets"].items()
        }
    private_path = path.with_name("credentials-private.pem")
    if not private_path.exists():
        raise HatSecretStoreError("The local Hat credential key is missing.")
    plaintext = _decrypt_bytes(
        private_path.read_text(encoding="utf-8"),
        payload["ciphertext_payload"],
    )
    try:
        bundle = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HatSecretStoreError("The encrypted Hat secret store is unreadable.") from exc
    if (
        not isinstance(bundle, dict)
        or bundle.get("schema") != BUNDLE_SCHEMA
        or not isinstance(bundle.get("credentials"), dict)
    ):
        raise HatSecretStoreError("The encrypted Hat secret store has an invalid format.")
    values = {
        normalize_secret_name(str(name)): str(value)
        for name, value in bundle["credentials"].items()
    }
    stored_names = sorted(str(name) for name in payload["names"])
    if sorted(values) != stored_names or payload.get("handle") != handle:
        raise HatSecretStoreError("The encrypted Hat secret names do not match the store.")
    return values


def _encrypted_store_payload(handle: str, values: dict[str, str]) -> dict[str, Any]:
    _, public_key_pem = ensure_hat_key_pair(handle)
    bundle = json.dumps(
        {
            "schema": BUNDLE_SCHEMA,
            "credentials": values,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema": STORE_SCHEMA,
        "handle": handle,
        "names": sorted(values),
        "ciphertext_payload": _encrypt_bytes(public_key_pem, bundle),
    }


def _write_store(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".secrets-",
        suffix=".json.tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        with suppress(OSError):
            temporary_path.unlink()


def set_hat_secret(handle: str, name: str, value: str) -> dict[str, Any]:
    """Create or replace one value in the encrypted Computer-local store."""
    clean_handle = normalize_hat_handle(handle)
    clean_name = normalize_secret_name(name)
    path = hat_secret_store_path(clean_handle)
    with _locked_store(path):
        payload = _read_store(path, handle=clean_handle)
        secrets = _store_values(path, payload, handle=clean_handle)
        operation = "updated" if clean_name in secrets else "created"
        secrets[clean_name] = str(value)
        _write_store(path, _encrypted_store_payload(clean_handle, secrets))
    return {
        "handle": clean_handle,
        "name": clean_name,
        "operation": operation,
        "value_available": False,
    }


def set_hat_secrets(handle: str, values: dict[str, str]) -> dict[str, Any]:
    """Create or replace an encrypted Hat bundle in one local write."""
    clean_handle = normalize_hat_handle(handle)
    if not isinstance(values, dict) or not values:
        raise HatSecretStoreError("The Hat credential bundle is empty.")
    clean_values: dict[str, str] = {}
    for raw_name, raw_value in values.items():
        clean_name = normalize_secret_name(raw_name)
        value = str(raw_value)
        if not value.strip():
            raise HatSecretStoreError(f"{clean_name} is empty.")
        clean_values[clean_name] = value

    path = hat_secret_store_path(clean_handle)
    with _locked_store(path):
        payload = _read_store(path, handle=clean_handle)
        existing = _store_values(path, payload, handle=clean_handle)
        created = sorted(name for name in clean_values if name not in existing)
        updated = sorted(name for name in clean_values if name in existing)
        existing.update(clean_values)
        _write_store(path, _encrypted_store_payload(clean_handle, existing))
    return {
        "handle": clean_handle,
        "names": sorted(clean_values),
        "count": len(clean_values),
        "created": created,
        "updated": updated,
        "value_available": False,
    }


def remove_hat_secret(handle: str, name: str) -> dict[str, Any]:
    """Delete one local value without ever returning or logging it."""
    clean_handle = normalize_hat_handle(handle)
    clean_name = normalize_secret_name(name)
    path = hat_secret_store_path(clean_handle)
    with _locked_store(path):
        payload = _read_store(path, handle=clean_handle)
        secrets = _store_values(path, payload, handle=clean_handle)
        removed = clean_name in secrets
        secrets.pop(clean_name, None)
        _write_store(path, _encrypted_store_payload(clean_handle, secrets))
    return {
        "handle": clean_handle,
        "name": clean_name,
        "removed": removed,
        "value_available": False,
    }


def list_hat_secret_names(handle: str) -> dict[str, Any]:
    """Return only names without initializing an absent credential store."""
    clean_handle = normalize_hat_handle(handle)
    path = hat_secret_store_path(clean_handle)
    with _locked_store(path):
        payload = _read_store(path, handle=clean_handle)
        if payload.get("schema") == LEGACY_STORE_SCHEMA:
            values = _store_values(path, payload, handle=clean_handle)
            names = sorted(values)
            if path.exists():
                payload = _encrypted_store_payload(clean_handle, values)
                _write_store(path, payload)
        else:
            names = sorted(normalize_secret_name(str(name)) for name in payload["names"])
    return {
        "handle": clean_handle,
        "names": names,
        "count": len(names),
        "value_available": False,
    }


def encrypt_hat_secret_bundle_for_public_key(
    handle: str,
    *,
    public_key_pem: str,
    expected_names: list[str],
) -> dict[str, Any]:
    """Re-encrypt one complete local Hat bundle for a consumer Computer.

    The plaintext exists only inside this Computer process while the store is
    locked. The return value contains ciphertext and value-blind metadata only.
    """
    clean_handle = normalize_hat_handle(handle)
    clean_expected = {
        normalize_secret_name(name) for name in expected_names if str(name or "").strip()
    }
    if not clean_expected:
        raise HatSecretStoreError("The Hat credential transfer has no names.")
    if "BEGIN PUBLIC KEY" not in str(public_key_pem or ""):
        raise HatSecretStoreError("The consumer credential public key is invalid.")

    path = hat_secret_store_path(clean_handle)
    values: dict[str, str] = {}
    plaintext = b""
    try:
        with _locked_store(path):
            payload = _read_store(path, handle=clean_handle)
            values = _store_values(path, payload, handle=clean_handle)
            if set(values) != clean_expected:
                raise HatSecretStoreError(
                    "The local Hat credential names do not match the transfer."
                )
            plaintext = json.dumps(
                {
                    "schema": BUNDLE_SCHEMA,
                    "credentials": values,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            ciphertext_payload = _encrypt_bytes(public_key_pem, plaintext)
    finally:
        plaintext = b""
        values.clear()

    return {
        "handle": clean_handle,
        "names": sorted(clean_expected),
        "count": len(clean_expected),
        "ciphertext_payload": ciphertext_payload,
        "value_available": False,
    }


def public_key_fingerprint_sha256(public_key_pem: str) -> str:
    """Return the stable public-key fingerprint shared with the platform."""

    clean_key = str(public_key_pem or "").strip()
    if "BEGIN PUBLIC KEY" not in clean_key or "END PUBLIC KEY" not in clean_key:
        raise HatSecretStoreError("The credential public key is invalid.")
    return hashlib.sha256(clean_key.encode("utf-8")).hexdigest()


def credential_names_fingerprint_sha256(names: list[str]) -> str:
    clean_names = sorted({normalize_secret_name(name) for name in names})
    return hashlib.sha256("\n".join(clean_names).encode("utf-8")).hexdigest()


def _authenticated_transfer_context(value: dict[str, Any]) -> dict[str, str]:
    if not isinstance(value, dict):
        raise HatSecretStoreError("The Hat credential transfer context is invalid.")
    context = {
        "handoff_id": str(value.get("handoff_id") or "").strip(),
        "installation_id": str(value.get("installation_id") or "").strip(),
        "hat_handle": normalize_hat_handle(str(value.get("hat_handle") or "")),
        "credential_names_sha256": str(value.get("credential_names_sha256") or "").strip().lower(),
        "consumer_public_key_fingerprint_sha256": str(
            value.get("consumer_public_key_fingerprint_sha256") or ""
        )
        .strip()
        .lower(),
    }
    if (
        not context["handoff_id"]
        or not context["installation_id"]
        or any(
            not re.fullmatch(r"[0-9a-f]{64}", context[field])
            for field in (
                "credential_names_sha256",
                "consumer_public_key_fingerprint_sha256",
            )
        )
    ):
        raise HatSecretStoreError("The Hat credential transfer context is invalid.")
    return context


def _envelope_signing_bytes(payload: dict[str, Any]) -> bytes:
    signed = {
        "schema": payload.get("schema"),
        "algorithm": payload.get("algorithm"),
        "encoding": payload.get("encoding"),
        "ciphertext_chunks_b64": payload.get("ciphertext_chunks_b64"),
        "creator_signature_algorithm": payload.get("creator_signature_algorithm"),
        "creator_public_key_fingerprint_sha256": payload.get(
            "creator_public_key_fingerprint_sha256"
        ),
        "context": payload.get("context"),
    }
    return json.dumps(signed, sort_keys=True, separators=(",", ":")).encode("utf-8")


def create_authenticated_hat_secret_envelope(
    handle: str,
    *,
    consumer_public_key_pem: str,
    expected_names: list[str],
    context: dict[str, Any],
    expected_creator_public_key_fingerprint_sha256: str,
) -> dict[str, Any]:
    """Encrypt for the consumer and sign with the Hat creator's local key."""

    clean_handle = normalize_hat_handle(handle)
    clean_context = _authenticated_transfer_context(context)
    if clean_context["hat_handle"] != clean_handle:
        raise HatSecretStoreError("The transfer context targets a different Hat.")
    if clean_context["credential_names_sha256"] != credential_names_fingerprint_sha256(
        expected_names
    ):
        raise HatSecretStoreError("The transfer credential names do not match.")
    consumer_fingerprint = public_key_fingerprint_sha256(consumer_public_key_pem)
    if clean_context["consumer_public_key_fingerprint_sha256"] != consumer_fingerprint:
        raise HatSecretStoreError("The transfer targets a different consumer key.")

    private_path, creator_public_key_pem = ensure_hat_key_pair(clean_handle)
    creator_fingerprint = public_key_fingerprint_sha256(creator_public_key_pem)
    if not hmac.compare_digest(
        creator_fingerprint,
        str(expected_creator_public_key_fingerprint_sha256 or "").strip().lower(),
    ):
        raise HatSecretStoreError("The platform creator identity does not match this Hat store.")
    encrypted = encrypt_hat_secret_bundle_for_public_key(
        clean_handle,
        public_key_pem=consumer_public_key_pem,
        expected_names=expected_names,
    )["ciphertext_payload"]
    envelope = {
        "schema": AUTHENTICATED_ENVELOPE_SCHEMA,
        "algorithm": encrypted["algorithm"],
        "encoding": encrypted["encoding"],
        "ciphertext_chunks_b64": encrypted["ciphertext_chunks_b64"],
        "creator_signature_algorithm": CREATOR_SIGNATURE_ALGORITHM,
        "creator_public_key_fingerprint_sha256": creator_fingerprint,
        "context": clean_context,
    }
    signature = _sign_bytes(
        private_path=private_path,
        payload=_envelope_signing_bytes(envelope),
    )
    envelope["creator_signature_b64"] = base64.b64encode(signature).decode("ascii")
    return envelope


def verify_authenticated_hat_secret_envelope(
    payload: dict[str, Any],
    *,
    creator_public_key_pem: str,
    expected_context: dict[str, Any],
) -> None:
    """Verify origin and exact installation context before consumer decrypt."""

    allowed_keys = {
        "schema",
        "algorithm",
        "encoding",
        "ciphertext_chunks_b64",
        "creator_signature_algorithm",
        "creator_public_key_fingerprint_sha256",
        "creator_signature_b64",
        "context",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != allowed_keys
        or payload.get("schema") != AUTHENTICATED_ENVELOPE_SCHEMA
        or payload.get("creator_signature_algorithm") != CREATOR_SIGNATURE_ALGORITHM
    ):
        raise HatSecretStoreError("The authenticated Hat credential envelope is invalid.")
    clean_context = _authenticated_transfer_context(expected_context)
    if payload.get("context") != clean_context:
        raise HatSecretStoreError("The Hat credential envelope context does not match.")
    expected_fingerprint = public_key_fingerprint_sha256(creator_public_key_pem)
    observed_fingerprint = (
        str(payload.get("creator_public_key_fingerprint_sha256") or "").strip().lower()
    )
    if not hmac.compare_digest(expected_fingerprint, observed_fingerprint):
        raise HatSecretStoreError("The Hat credential creator identity does not match.")
    try:
        signature = base64.b64decode(str(payload.get("creator_signature_b64") or ""), validate=True)
    except (TypeError, ValueError) as exc:
        raise HatSecretStoreError("The Hat credential creator signature is invalid.") from exc
    if not signature or not _verify_signature(
        public_key_pem=creator_public_key_pem,
        payload=_envelope_signing_bytes(payload),
        signature=signature,
    ):
        raise HatSecretStoreError("The Hat credential creator signature is invalid.")


def _sign_bytes(*, private_path: Path, payload: bytes) -> bytes:
    openssl = shutil.which("openssl")
    if not openssl:
        raise HatSecretStoreError("openssl is required for encrypted Hat credentials.")
    return _run_openssl_bytes(
        [
            openssl,
            "dgst",
            "-sha256",
            "-sign",
            str(private_path),
            "-sigopt",
            "rsa_padding_mode:pss",
            "-sigopt",
            "rsa_pss_saltlen:-1",
        ],
        payload,
    )


def _verify_signature(*, public_key_pem: str, payload: bytes, signature: bytes) -> bool:
    openssl = shutil.which("openssl")
    if not openssl:
        raise HatSecretStoreError("openssl is required for encrypted Hat credentials.")
    with tempfile.TemporaryDirectory(prefix="tinyhat-hat-verify-") as temp_dir:
        directory = Path(temp_dir)
        public_path = directory / "public.pem"
        signature_path = directory / "signature.bin"
        public_path.write_text(public_key_pem, encoding="utf-8")
        public_path.chmod(0o600)
        signature_path.write_bytes(signature)
        signature_path.chmod(0o600)
        try:
            completed = subprocess.run(
                [
                    openssl,
                    "dgst",
                    "-sha256",
                    "-verify",
                    str(public_path),
                    "-signature",
                    str(signature_path),
                    "-sigopt",
                    "rsa_padding_mode:pss",
                    "-sigopt",
                    "rsa_pss_saltlen:-1",
                ],
                input=payload,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HatSecretStoreError(
                "Local Hat credential signature verification failed."
            ) from exc
    return completed.returncode == 0


def _generate_key_pair() -> tuple[str, str]:
    openssl = shutil.which("openssl")
    if not openssl:
        raise HatSecretStoreError("openssl is required for encrypted Hat credentials.")
    with tempfile.TemporaryDirectory(prefix="tinyhat-hat-key-") as temp_dir:
        private_key = Path(temp_dir) / "private.pem"
        public_key = Path(temp_dir) / "public.pem"
        _run_openssl(
            [
                openssl,
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:3072",
                "-out",
                str(private_key),
            ]
        )
        _run_openssl(
            [
                openssl,
                "rsa",
                "-pubout",
                "-in",
                str(private_key),
                "-out",
                str(public_key),
            ]
        )
        return (
            private_key.read_text(encoding="utf-8"),
            public_key.read_text(encoding="utf-8"),
        )


def _write_key_material(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}-",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        with suppress(OSError):
            temporary_path.unlink()


def _encrypt_bytes(public_key_pem: str, plaintext: bytes) -> dict[str, Any]:
    openssl = shutil.which("openssl")
    if not openssl:
        raise HatSecretStoreError("openssl is required for encrypted Hat credentials.")
    chunks = [
        plaintext[index : index + RSA_OAEP_CHUNK_BYTES]
        for index in range(0, len(plaintext), RSA_OAEP_CHUNK_BYTES)
    ] or [b""]
    encrypted_chunks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="tinyhat-hat-encrypt-") as temp_dir:
        directory = Path(temp_dir)
        public_key = directory / "public.pem"
        public_key.write_text(public_key_pem, encoding="utf-8")
        public_key.chmod(0o600)
        for chunk in chunks:
            encrypted = _run_openssl_bytes(
                [
                    openssl,
                    "pkeyutl",
                    "-encrypt",
                    "-pubin",
                    "-inkey",
                    str(public_key),
                    "-pkeyopt",
                    "rsa_padding_mode:oaep",
                    "-pkeyopt",
                    "rsa_oaep_md:sha256",
                ],
                chunk,
            )
            encrypted_chunks.append(base64.b64encode(encrypted).decode("ascii"))
    return {
        "schema": "tinyhat_hat_credentials_ciphertext_v1",
        "algorithm": KEY_ALGORITHM,
        "encoding": "base64",
        "ciphertext_chunks_b64": encrypted_chunks,
    }


def _decrypt_bytes(private_key_pem: str, payload: dict[str, Any]) -> bytes:
    if (
        payload.get("schema") != "tinyhat_hat_credentials_ciphertext_v1"
        or payload.get("algorithm") != KEY_ALGORITHM
        or not isinstance(payload.get("ciphertext_chunks_b64"), list)
        or not payload["ciphertext_chunks_b64"]
    ):
        raise HatSecretStoreError("The encrypted Hat credential payload is invalid.")
    openssl = shutil.which("openssl")
    if not openssl:
        raise HatSecretStoreError("openssl is required for encrypted Hat credentials.")
    plaintext_chunks: list[bytes] = []
    with tempfile.TemporaryDirectory(prefix="tinyhat-hat-decrypt-") as temp_dir:
        directory = Path(temp_dir)
        private_key = directory / "private.pem"
        private_key.write_text(private_key_pem, encoding="utf-8")
        private_key.chmod(0o600)
        for encoded in payload["ciphertext_chunks_b64"]:
            try:
                ciphertext = base64.b64decode(str(encoded), validate=True)
            except (ValueError, TypeError) as exc:
                raise HatSecretStoreError(
                    "The encrypted Hat credential payload is invalid."
                ) from exc
            plaintext_chunks.append(
                _run_openssl_bytes(
                    [
                        openssl,
                        "pkeyutl",
                        "-decrypt",
                        "-inkey",
                        str(private_key),
                        "-pkeyopt",
                        "rsa_padding_mode:oaep",
                        "-pkeyopt",
                        "rsa_oaep_md:sha256",
                    ],
                    ciphertext,
                )
            )
    return b"".join(plaintext_chunks)


def _run_openssl(command: list[str]) -> None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HatSecretStoreError("Local Hat credential encryption failed.") from exc
    if completed.returncode != 0:
        raise HatSecretStoreError("Local Hat credential encryption failed.")


def _run_openssl_bytes(command: list[str], payload: bytes) -> bytes:
    try:
        completed = subprocess.run(
            command,
            input=payload,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HatSecretStoreError("Local Hat credential encryption failed.") from exc
    if completed.returncode != 0:
        raise HatSecretStoreError("Local Hat credential encryption failed.")
    return completed.stdout


def delete_hat_secret_store(handle: str) -> dict[str, Any]:
    """Remove every creator-local value and key belonging to one retired Hat."""
    clean_handle = normalize_hat_handle(handle)
    root = _store_root().resolve()
    directory = hat_secret_store_path(clean_handle).parent
    if not directory.exists():
        return {
            "handle": clean_handle,
            "removed": False,
            "value_available": False,
        }
    try:
        directory.resolve().relative_to(root)
    except ValueError as exc:
        raise HatSecretStoreError("The local Hat store path is unsafe.") from exc
    if directory.is_symlink():
        raise HatSecretStoreError("The local Hat store path is unsafe.")
    try:
        shutil.rmtree(directory)
        account_directory = directory.parent
        if account_directory != root and not any(account_directory.iterdir()):
            account_directory.rmdir()
    except OSError as exc:
        raise HatSecretStoreError("The local Hat secret store could not be removed.") from exc
    return {
        "handle": clean_handle,
        "removed": True,
        "value_available": False,
    }


def rename_hat_secret_store(old_handle: str, new_handle: str) -> dict[str, Any]:
    """Move one encrypted Hat store without exposing or replacing its values."""
    clean_old = normalize_hat_handle(old_handle)
    clean_new = normalize_hat_handle(new_handle)
    if clean_old == clean_new:
        return {
            "old_handle": clean_old,
            "handle": clean_new,
            "renamed": False,
            "already_current": True,
            "value_available": False,
        }

    root = _store_root()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    resolved_root = root.resolve()
    old_directory = hat_secret_store_path(clean_old).parent
    new_directory = hat_secret_store_path(clean_new).parent
    for directory in (old_directory, new_directory):
        try:
            directory.resolve(strict=False).relative_to(resolved_root)
        except ValueError as exc:
            raise HatSecretStoreError("The local Hat store path is unsafe.") from exc
        if directory.is_symlink():
            raise HatSecretStoreError("The local Hat store path is unsafe.")

    rename_lock_path = root / ".handle-rename.lock"
    descriptor = os.open(rename_lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(rename_lock_path, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as rename_lock:
        fcntl.flock(rename_lock.fileno(), fcntl.LOCK_EX)
        if not old_directory.exists():
            return {
                "old_handle": clean_old,
                "handle": clean_new,
                "renamed": False,
                "already_current": new_directory.exists(),
                "value_available": False,
            }
        if new_directory.exists():
            raise HatSecretStoreError("The new Hat handle already has a local credential store.")

        old_path = old_directory / "secrets.json"
        with _locked_store(old_path):
            payload = _read_store(old_path, handle=clean_old)
            values = _store_values(old_path, payload, handle=clean_old)
            new_directory.parent.mkdir(parents=True, exist_ok=True)
            moved = False
            try:
                os.replace(old_directory, new_directory)
                moved = True
                new_path = new_directory / "secrets.json"
                _write_store(
                    new_path,
                    _encrypted_store_payload(clean_new, values),
                )
            except Exception as exc:
                if moved and new_directory.exists() and not old_directory.exists():
                    try:
                        os.replace(new_directory, old_directory)
                        _write_store(
                            old_path,
                            _encrypted_store_payload(clean_old, values),
                        )
                    except Exception as rollback_exc:
                        raise HatSecretStoreError(
                            "The local Hat credential store rename could not be rolled back safely."
                        ) from rollback_exc
                if isinstance(exc, HatSecretStoreError):
                    raise
                raise HatSecretStoreError(
                    "The local Hat credential store could not be renamed."
                ) from exc

    return {
        "old_handle": clean_old,
        "handle": clean_new,
        "renamed": True,
        "already_current": False,
        "value_available": False,
    }


__all__ = [
    "HatSecretStoreError",
    "delete_hat_secret_store",
    "create_authenticated_hat_secret_envelope",
    "credential_names_fingerprint_sha256",
    "ensure_hat_key_pair",
    "hat_secret_store_path",
    "list_hat_secret_names",
    "normalize_hat_handle",
    "normalize_secret_name",
    "remove_hat_secret",
    "rename_hat_secret_store",
    "set_hat_secret",
    "set_hat_secrets",
    "public_key_fingerprint_sha256",
    "verify_authenticated_hat_secret_envelope",
]
