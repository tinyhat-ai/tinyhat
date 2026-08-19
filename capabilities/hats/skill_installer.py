"""Install Hat repository skills into Hermes without overwriting user skills."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from .secrets import normalize_hat_handle

MAX_SKILLS = 50
MAX_FILES_PER_SKILL = 200
MAX_BYTES_PER_SKILL = 10 * 1024 * 1024
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


class HatSkillInstallError(RuntimeError):
    """One Hat skill package could not be installed safely."""


@contextmanager
def _installation_lock(handle: str):
    digest = hashlib.sha256(handle.encode("utf-8")).hexdigest()[:16]
    directory = Path.home() / ".tinyhat" / "installed-hats"
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise HatSkillInstallError("The Hat installation state directory is unsafe.")
    directory.chmod(0o700)
    path = directory / f".{digest}.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _skills_root() -> Path:
    configured = os.getenv("HERMES_SKILLS_ROOT", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".hermes" / "skills"


def _state_path(handle: str) -> Path:
    digest = hashlib.sha256(handle.encode("utf-8")).hexdigest()[:16]
    return Path.home() / ".tinyhat" / "installed-hats" / f"{digest}.json"


def _skill_sources(checkout: Path) -> list[Path]:
    skills_dir = checkout / "skills"
    if not skills_dir.is_dir() or skills_dir.is_symlink():
        return []
    sources = sorted(
        item
        for item in skills_dir.iterdir()
        if item.is_dir()
        and not item.is_symlink()
        and SAFE_SEGMENT_RE.fullmatch(item.name)
        and (item / "SKILL.md").is_file()
        and not (item / "SKILL.md").is_symlink()
    )
    if len(sources) > MAX_SKILLS:
        raise HatSkillInstallError("This Hat contains too many skills.")
    return sources


def _validate_tree(source: Path) -> None:
    file_count = 0
    byte_count = 0
    for path in source.rglob("*"):
        if path.is_symlink():
            raise HatSkillInstallError("Hat skills may not contain symbolic links.")
        if not path.is_file():
            continue
        file_count += 1
        byte_count += path.stat().st_size
        if file_count > MAX_FILES_PER_SKILL or byte_count > MAX_BYTES_PER_SKILL:
            raise HatSkillInstallError("One Hat skill package is too large.")


def install_hat_skills(handle: str, checkout_path: str) -> dict[str, Any]:
    """Copy namespaced Hat skills transactionally into Hermes's skill root."""
    clean_handle = normalize_hat_handle(handle)
    with _installation_lock(clean_handle):
        return _install_hat_skills_locked(clean_handle, checkout_path)


def _install_hat_skills_locked(handle: str, checkout_path: str) -> dict[str, Any]:
    checkout = Path(checkout_path).expanduser().resolve(strict=True)
    if not checkout.is_dir():
        raise HatSkillInstallError("The Hat repository checkout is unavailable.")
    sources = _skill_sources(checkout)
    root = _skills_root()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise HatSkillInstallError("The Hermes skill directory is unsafe.")
    root.chmod(0o700)
    prefix = "hat-" + hashlib.sha256(handle.encode("utf-8")).hexdigest()[:12]
    desired = {f"{prefix}-{source.name}": source for source in sources}
    state_path = _state_path(handle)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.chmod(0o700)

    previous: set[str] = set()
    with suppress(OSError, json.JSONDecodeError, TypeError):
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        previous = {
            str(name)
            for name in saved.get("installed_names", [])
            if str(name).startswith(f"{prefix}-")
        }

    transaction = Path(tempfile.mkdtemp(prefix=f".{prefix}-install-", dir=root))
    staged_root = transaction / "staged"
    backup_root = transaction / "backups"
    staged_root.mkdir(mode=0o700)
    backup_root.mkdir(mode=0o700)
    installed: list[str] = []
    backed_up: list[str] = []
    cleanup_transaction = True
    try:
        # Copy and validate every package before replacing any active skill. A
        # malformed later package must not leave an earlier package upgraded.
        for target_name, source in desired.items():
            _validate_tree(source)
            shutil.copytree(source, staged_root / target_name)

        for target_name in desired:
            target = root / target_name
            backup = backup_root / target_name
            if target.is_symlink():
                raise HatSkillInstallError("A Hat skill destination is unsafe.")
            if target.exists():
                target.rename(backup)
                backed_up.append(target_name)
            (staged_root / target_name).rename(target)
            installed.append(target_name)
    except Exception:
        try:
            for target_name in reversed(installed):
                target = root / target_name
                if target.is_symlink():
                    target.unlink()
                elif target.exists():
                    shutil.rmtree(target)
            for target_name in reversed(backed_up):
                backup = backup_root / target_name
                target = root / target_name
                if backup.exists() and not target.exists():
                    backup.rename(target)
        except Exception as rollback_error:
            cleanup_transaction = False
            raise HatSkillInstallError(
                f"Hat skill rollback needs recovery from {transaction}."
            ) from rollback_error
        raise
    finally:
        if cleanup_transaction:
            with suppress(OSError):
                shutil.rmtree(transaction)

    for stale_name in previous - set(installed):
        stale = root / stale_name
        if stale.parent == root and stale.name.startswith(f"{prefix}-"):
            with suppress(OSError):
                shutil.rmtree(stale)

    payload = {
        "schema": "tinyhat_installed_hat_skills_v1",
        "hat_handle": handle,
        "checkout_path": str(checkout),
        "installed_names": sorted(installed),
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".installed-hat-", suffix=".json", dir=state_path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, sort_keys=True)
            output.write("\n")
        os.replace(temporary_path, state_path)
    finally:
        with suppress(OSError):
            temporary_path.unlink()
    return {
        "hat_handle": handle,
        "installed_names": sorted(installed),
        "count": len(installed),
        "value_available": False,
    }


__all__ = ["HatSkillInstallError", "install_hat_skills"]
