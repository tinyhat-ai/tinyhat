"""Computer-local secret storage for one-customer Hats.

Only the encrypted handoff worker calls ``set_hat_secret`` with plaintext.
Every public return shape is value-blind: names, counts, paths, and booleans.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

HAT_HANDLE_RE = re.compile(
    r"^(?P<account>[a-z0-9][a-z0-9_-]{0,46})/hats/" r"(?P<key>[a-z0-9][a-z0-9_-]{0,46})$"
)
SECRET_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,126}$")


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
            "schema": "tinyhat_hat_secrets_v1",
            "handle": handle,
            "secrets": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HatSecretStoreError("The local Hat secret store is unreadable.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "tinyhat_hat_secrets_v1"
        or payload.get("handle") != handle
        or not isinstance(payload.get("secrets"), dict)
    ):
        raise HatSecretStoreError("The local Hat secret store has an invalid format.")
    return payload


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
    """Create or replace one plaintext value in the Computer-local store."""
    clean_handle = normalize_hat_handle(handle)
    clean_name = normalize_secret_name(name)
    path = hat_secret_store_path(clean_handle)
    with _locked_store(path):
        payload = _read_store(path, handle=clean_handle)
        secrets = dict(payload["secrets"])
        operation = "updated" if clean_name in secrets else "created"
        secrets[clean_name] = str(value)
        payload["secrets"] = secrets
        _write_store(path, payload)
    return {
        "handle": clean_handle,
        "name": clean_name,
        "operation": operation,
        "value_available": False,
    }


def remove_hat_secret(handle: str, name: str) -> dict[str, Any]:
    """Delete one local value without ever returning or logging it."""
    clean_handle = normalize_hat_handle(handle)
    clean_name = normalize_secret_name(name)
    path = hat_secret_store_path(clean_handle)
    with _locked_store(path):
        payload = _read_store(path, handle=clean_handle)
        secrets = dict(payload["secrets"])
        removed = clean_name in secrets
        secrets.pop(clean_name, None)
        payload["secrets"] = secrets
        _write_store(path, payload)
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
    return {
        "handle": clean_handle,
        "names": sorted(str(name) for name in payload["secrets"]),
        "count": len(payload["secrets"]),
        "value_available": False,
    }


__all__ = [
    "HatSecretStoreError",
    "hat_secret_store_path",
    "list_hat_secret_names",
    "normalize_hat_handle",
    "normalize_secret_name",
    "remove_hat_secret",
    "set_hat_secret",
]
