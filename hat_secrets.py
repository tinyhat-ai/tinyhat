"""Encrypted Computer-local secret storage for one-customer Hats.

Only the encrypted handoff worker calls ``set_hat_secret`` with plaintext.
Values are immediately re-encrypted with the Hat's stable local key pair
before the atomic store write. Every public return shape is value-blind:
names, counts, paths, and booleans.
"""

from __future__ import annotations

import base64
import fcntl
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
            raise HatSecretStoreError(
                "The local Hat credential key pair is incomplete."
            )
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
    if payload.get("schema") == LEGACY_STORE_SCHEMA and isinstance(
        payload.get("secrets"), dict
    ):
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
        raise HatSecretStoreError(
            "The encrypted Hat secret store has an invalid format."
        )
    values = {
        normalize_secret_name(str(name)): str(value)
        for name, value in bundle["credentials"].items()
    }
    stored_names = sorted(str(name) for name in payload["names"])
    if sorted(values) != stored_names or payload.get("handle") != handle:
        raise HatSecretStoreError(
            "The encrypted Hat secret names do not match the store."
        )
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
    """Return only names from the local store for diagnostics and tests."""
    clean_handle = normalize_hat_handle(handle)
    path = hat_secret_store_path(clean_handle)
    with _locked_store(path):
        payload = _read_store(path, handle=clean_handle)
        if payload.get("schema") == LEGACY_STORE_SCHEMA:
            values = _store_values(path, payload, handle=clean_handle)
            payload = _encrypted_store_payload(clean_handle, values)
            _write_store(path, payload)
        names = sorted(str(name) for name in payload["names"])
    return {
        "handle": clean_handle,
        "names": names,
        "count": len(names),
        "value_available": False,
    }


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
    """Remove every local value and key belonging to one deleted Hat."""
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


__all__ = [
    "HatSecretStoreError",
    "delete_hat_secret_store",
    "ensure_hat_key_pair",
    "hat_secret_store_path",
    "list_hat_secret_names",
    "normalize_hat_handle",
    "normalize_secret_name",
    "remove_hat_secret",
    "set_hat_secret",
    "set_hat_secrets",
]
