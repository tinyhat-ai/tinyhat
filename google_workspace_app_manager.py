"""Reproducible manager for Tinyhat's pinned Google Workspace CLI integration."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import io
import json
import os
import stat
import tarfile
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib import parse, request

from .tool_errors import tool_error_json

MANAGER_SCHEMA = "tinyhat_google_workspace_app_manager_v1"
MANIFEST_SCHEMA = "tinyhat_google_workspace_app_install_v1"
MANAGER_ACTIONS = ("status", "install", "uninstall")
PINNED_GWS_VERSION = "0.22.5"
PINNED_ARCHIVE_SHA256 = (
    "de78ecdbd2f1a84cca0063a7ecbc440240fc14b6ebccbb17f4646b792a8c5c1f"
)
PINNED_BINARY_SHA256 = (
    "ab59c4bab4e7848740ba8cc3ef186152dab90121c45835b49bd1bf2a5c259b86"
)
PINNED_ARCHIVE_URL = (
    "https://github.com/googleworkspace/cli/releases/download/v0.22.5/"
    "google-workspace-cli-x86_64-unknown-linux-gnu.tar.gz"
)
PINNED_AARCH64_ARCHIVE_URL = (
    "https://github.com/googleworkspace/cli/releases/download/v0.22.5/"
    "google-workspace-cli-aarch64-unknown-linux-gnu.tar.gz"
)
PINNED_AARCH64_ARCHIVE_SHA256 = (
    "94490295d9580e1e88574e715a0a162991747d12d62f8c7b8dcc8268b6c1cea0"
)
PINNED_AARCH64_BINARY_SHA256 = (
    "b68337faf1436fb2b3a287207cd57fef784a20fb4ab4f2429e51c4e0cfa0b50b"
)
OFFICIAL_SKILL_BASE_URL = (
    "https://raw.githubusercontent.com/googleworkspace/cli/v0.22.5/skills"
)
PINNED_OFFICIAL_SKILLS = {
    "gws-calendar": "2be9bcdd12a425169c79473c4e56200715e4a3b6c04ed2988839b12ce8aea6b8",
    "gws-calendar-agenda": "df3a57f21738db339095055e543c5d9a2f1bff807504966f3bcb95ab7687f97a",
    "gws-gmail": "d37f41ad13fd3467d430e60dfb985d7818ef6976bae40182f8e46a410b8caa16",
    "gws-gmail-read": "11707bc21b93381fa56a309364002b255b1a90c52aca51afa5965087657a69a5",
    "gws-gmail-send": "5002f29ed58e3f14b826d4eadd917dd5f3e7f3ec8c6cbad7c61e4f340be519aa",
    "gws-drive": "d37fad56bb9547d2e169bfd04fbf1f4a377281456765c6243f092f32c973cdac",
}
TINYHAT_SHARED_SKILL_SHA256 = (
    "cbbc7fbc2fe9f4fa759754eeef9f34da1661d777cec60ac2ba6f73228fc44948"
)
TINYHAT_SHARED_SKILL_SOURCE = (
    Path(__file__).resolve().parent
    / "skills"
    / "tinyhat-google-workspace"
    / "assets"
    / "gws-shared"
    / "SKILL.md"
)
INSTALL_ROOT = Path("/opt/tinyhat")
BINARY_PATH = INSTALL_ROOT / "bin" / "gws"
STATE_DIR = INSTALL_ROOT / "state"
MANIFEST_PATH = STATE_DIR / "google-workspace-app.json"
QUARANTINE_DIR = INSTALL_ROOT / "quarantine"
HERMES_SKILLS_ROOT = Path(
    os.environ.get("TINYHAT_HERMES_HOME", str(Path.home() / ".hermes"))
) / "skills"
TRUSTED_HERMES_HOMES = (Path("/root/.hermes"),)
DOWNLOAD_TIMEOUT_SECONDS = 30
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_BINARY_BYTES = 64 * 1024 * 1024
MAX_SKILL_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_MANAGED_COMPONENT_BYTES = 64 * 1024 * 1024
OWNER_ONLY_MODE = 0o600
ROOT_EXECUTABLE_MODE = 0o755
ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
}


class GoogleWorkspaceAppManagerError(RuntimeError):
    """One safe managed-app lifecycle failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.public_message = message
        super().__init__(code)


@dataclass(frozen=True)
class ManagedPayload:
    """One verified file ready for transactional installation."""

    component: str
    path: Path
    content: bytes
    mode: int
    source: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class GwsReleaseArtifact:
    """One hardcoded official release artifact for a supported Linux architecture."""

    architecture: str
    archive_url: str
    archive_sha256: str
    binary_sha256: str


@dataclass(frozen=True)
class ManagedGwsBinary:
    """Open verified executable held under a shared manager lock."""

    fd: int
    proc_path: str
    sha256: str


PINNED_GWS_ARTIFACTS = {
    "x86_64": GwsReleaseArtifact(
        architecture="x86_64",
        archive_url=PINNED_ARCHIVE_URL,
        archive_sha256=PINNED_ARCHIVE_SHA256,
        binary_sha256=PINNED_BINARY_SHA256,
    ),
    "aarch64": GwsReleaseArtifact(
        architecture="aarch64",
        archive_url=PINNED_AARCH64_ARCHIVE_URL,
        archive_sha256=PINNED_AARCH64_ARCHIVE_SHA256,
        binary_sha256=PINNED_AARCH64_BINARY_SHA256,
    ),
}
TRUSTED_MANAGED_RELEASES = {
    "0.22.5": {
        "artifacts": dict(PINNED_GWS_ARTIFACTS),
        "skills": dict(PINNED_OFFICIAL_SKILLS),
        "shared_sha256": TINYHAT_SHARED_SKILL_SHA256,
    }
}


class _HttpsOnlyRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: PLR0913
        _validate_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def google_workspace_app_manager(
    args: dict[str, Any] | None = None,
    **_: Any,
) -> str:
    """Inspect or mutate the pinned managed gws installation."""
    payload = args if isinstance(args, dict) else {}
    raw_action = payload.get("action")
    if not isinstance(raw_action, str) or not raw_action.strip():
        return tool_error_json(
            tool="tinyhat_google_workspace_app_manager",
            error_name="missing_required_parameter",
            message="Choose status, install, or uninstall for the managed gws app.",
            missing=["action"],
            example_call={"action": "status"},
        )
    action = raw_action.strip().lower()
    if action not in MANAGER_ACTIONS:
        return tool_error_json(
            tool="tinyhat_google_workspace_app_manager",
            error_name="invalid_parameter",
            message="Unsupported managed gws action. Use status, install, or uninstall.",
            expected={"action": list(MANAGER_ACTIONS)},
            example_call={"action": "status"},
        )
    if action in {"install", "uninstall"} and payload.get("confirmed") is not True:
        verb = "install the pinned Google Workspace CLI and official operation skills"
        if action == "uninstall":
            verb = "remove only unchanged files installed by Tinyhat"
        return tool_error_json(
            tool="tinyhat_google_workspace_app_manager",
            error_name="confirmation_required",
            message=f"Ask the user to confirm that Tinyhat may {verb}.",
            example_call={"action": action, "confirmed": True},
        )
    try:
        if action == "status":
            result = managed_app_status()
        elif action == "install":
            result = install_managed_app()
        else:
            result = uninstall_managed_app()
    except GoogleWorkspaceAppManagerError as exc:
        result = {
            "schema": MANAGER_SCHEMA,
            "action": action,
            "status": "failed",
            "error": exc.code,
            "message": exc.public_message,
        }
    except Exception:
        result = {
            "schema": MANAGER_SCHEMA,
            "action": action,
            "status": "failed",
            "error": "unavailable",
            "message": "The managed Google Workspace app operation failed safely.",
        }
    return json.dumps(result, sort_keys=True)


def _require_supported_host() -> GwsReleaseArtifact:
    try:
        host = os.uname()
    except AttributeError as exc:
        raise GoogleWorkspaceAppManagerError(
            "unsupported_platform",
            "The managed Google Workspace app supports Linux x86_64 and aarch64 Computers.",
        ) from exc
    aliases = {"amd64": "x86_64", "arm64": "aarch64"}
    architecture = aliases.get(host.machine.lower(), host.machine.lower())
    artifact = PINNED_GWS_ARTIFACTS.get(architecture)
    if host.sysname != "Linux" or artifact is None:
        raise GoogleWorkspaceAppManagerError(
            "unsupported_platform",
            "The managed Google Workspace app supports Linux x86_64 and aarch64 Computers.",
        )
    if os.geteuid() != 0:
        raise GoogleWorkspaceAppManagerError(
            "root_required",
            "The managed Google Workspace app must be installed by the Computer service as root.",
        )
    configured_home = HERMES_SKILLS_ROOT.parent
    if (
        not configured_home.is_absolute()
        or configured_home not in TRUSTED_HERMES_HOMES
    ):
        raise GoogleWorkspaceAppManagerError(
            "unsafe_path",
            "The managed Google Workspace app requires a trusted Hermes home.",
        )
    _validate_trusted_hermes_home(configured_home)
    _validate_fixed_install_root()
    return artifact


def _validate_trusted_hermes_home(configured_home: Path) -> None:
    """Reject symlinked or writable ancestors before root writes operation skills."""
    candidates = [configured_home, *configured_home.parents]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            info = candidate.lstat()
        except OSError as exc:
            raise GoogleWorkspaceAppManagerError(
                "unsafe_path", "The trusted Hermes home could not be validated."
            ) from exc
        if (
            not stat.S_ISDIR(info.st_mode)
            or candidate.is_symlink()
            or info.st_uid != 0
            or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise GoogleWorkspaceAppManagerError(
                "unsafe_path", "The trusted Hermes home has an unsafe ancestor."
            )


def _validate_fixed_install_root() -> None:
    if (
        Path("/opt/tinyhat") != INSTALL_ROOT
        or Path("/opt/tinyhat/bin/gws") != BINARY_PATH
        or Path("/opt/tinyhat/state") != STATE_DIR
        or Path("/opt/tinyhat/state/google-workspace-app.json") != MANIFEST_PATH
    ):
        raise GoogleWorkspaceAppManagerError(
            "unsafe_path", "The managed Google Workspace install root is not fixed."
        )
    for candidate in [INSTALL_ROOT, *INSTALL_ROOT.parents]:
        if not candidate.exists():
            continue
        info = candidate.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or candidate.is_symlink()
            or info.st_uid != 0
            or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise GoogleWorkspaceAppManagerError(
                "unsafe_path", "The managed Google Workspace install root is unsafe."
            )


@contextlib.contextmanager
def managed_app_lock(*, exclusive: bool) -> Iterator[None]:
    """Serialize manager mutations and hold bridge executions against uninstall."""
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    _verify_managed_directory(STATE_DIR, mode=0o700)
    lock_path = STATE_DIR / "google-workspace-app.lock"
    fd = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(fd, 0o600)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != OWNER_ONLY_MODE
        ):
            raise GoogleWorkspaceAppManagerError(
                "unsafe_path", "The managed Google Workspace app lock is unsafe."
            )
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _managed_targets() -> dict[str, Path]:
    targets = {"gws": BINARY_PATH}
    skill_names = set(PINNED_OFFICIAL_SKILLS)
    for release in TRUSTED_MANAGED_RELEASES.values():
        skills = release.get("skills")
        if isinstance(skills, dict):
            skill_names.update(str(name) for name in skills)
    for name in sorted(skill_names):
        targets[f"skill:{name}"] = HERMES_SKILLS_ROOT / name / "SKILL.md"
    targets["skill:gws-shared"] = HERMES_SKILLS_ROOT / "gws-shared" / "SKILL.md"
    return targets


def managed_app_status() -> dict[str, Any]:
    artifact = _require_supported_host()
    with managed_app_lock(exclusive=False):
        return _managed_app_status_locked(artifact)


def _managed_app_status_locked(artifact: GwsReleaseArtifact) -> dict[str, Any]:
    manifest = _read_manifest(optional=True)
    targets = _managed_targets()
    if manifest is None:
        return {
            "schema": MANAGER_SCHEMA,
            "action": "status",
            "status": "not_installed",
            "managed": False,
            "version": PINNED_GWS_VERSION,
            "architecture": artifact.architecture,
            "unmanaged_components_present": any(
                path.exists() or path.is_symlink() for path in targets.values()
            ),
        }
    records = _validate_manifest(manifest, artifact=artifact)
    component_status = {
        component: _file_matches_record(targets[component], record)
        for component, record in records.items()
    }
    missing_components = sorted(set(targets) - set(records))
    changed = sorted(
        [component for component, matches in component_status.items() if not matches]
        + missing_components
    )
    return {
        "schema": MANAGER_SCHEMA,
        "action": "status",
        "status": "installed" if not changed else "integrity_mismatch",
        "managed": True,
        "version": manifest["version"],
        "architecture": artifact.architecture,
        "binary_ready": component_status.get("gws", False),
        "skills_ready": all(
            component_status.get(f"skill:{name}", False)
            for name in [*PINNED_OFFICIAL_SKILLS, "gws-shared"]
        ),
        "changed_components": changed,
    }


def install_managed_app() -> dict[str, Any]:
    artifact = _require_supported_host()
    with managed_app_lock(exclusive=True):
        _recover_interrupted_install(artifact)
        return _install_managed_app_locked(artifact)


def _install_managed_app_locked(artifact: GwsReleaseArtifact) -> dict[str, Any]:
    archive = _download_bytes(artifact.archive_url, max_bytes=MAX_ARCHIVE_BYTES)
    _require_sha256(archive, artifact.archive_sha256, label="gws release archive")
    binary = _extract_gws_binary(archive)
    _require_sha256(binary, artifact.binary_sha256, label="extracted gws binary")
    payloads = [
        ManagedPayload("gws", BINARY_PATH, binary, 0o755, artifact.archive_url)
    ]
    for name, expected_hash in PINNED_OFFICIAL_SKILLS.items():
        url = f"{OFFICIAL_SKILL_BASE_URL}/{name}/SKILL.md"
        content = _download_bytes(url, max_bytes=MAX_SKILL_BYTES)
        _require_sha256(content, expected_hash, label=name)
        payloads.append(
            ManagedPayload(
                f"skill:{name}",
                HERMES_SKILLS_ROOT / name / "SKILL.md",
                content,
                0o644,
                url,
            )
        )
    try:
        shared = TINYHAT_SHARED_SKILL_SOURCE.read_bytes()
    except OSError as exc:
        raise GoogleWorkspaceAppManagerError(
            "package_invalid", "The Tinyhat gws integration shim is unavailable."
        ) from exc
    _require_sha256(shared, TINYHAT_SHARED_SKILL_SHA256, label="gws-shared")
    payloads.append(
        ManagedPayload(
            "skill:gws-shared",
            HERMES_SKILLS_ROOT / "gws-shared" / "SKILL.md",
            shared,
            0o644,
            "tinyhat-plugin:gws-shared",
        )
    )

    existing = _read_manifest(optional=True)
    records = (
        _validate_manifest(existing, artifact=artifact) if existing is not None else {}
    )
    _preflight_install(payloads, records)
    installed_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "version": PINNED_GWS_VERSION,
        "platform": "linux",
        "architecture": artifact.architecture,
        "archive_sha256": artifact.archive_sha256,
        "installed_at": installed_at,
        "components": {
            item.component: {
                "path": str(item.path),
                "sha256": item.sha256,
                "mode": item.mode,
                "source": item.source,
            }
            for item in payloads
        },
    }
    _transactional_install(payloads, manifest)
    return {
        "schema": MANAGER_SCHEMA,
        "action": "install",
        "status": "installed",
        "managed": True,
        "version": PINNED_GWS_VERSION,
        "architecture": artifact.architecture,
        "binary_ready": True,
        "installed_skills": sorted([*PINNED_OFFICIAL_SKILLS, "gws-shared"]),
        "message": (
            "The pinned Google Workspace CLI and verified operation skills are ready. "
            "Use Tinyhat's token bridge; never run gws auth."
        ),
    }


def uninstall_managed_app() -> dict[str, Any]:
    artifact = _require_supported_host()
    with managed_app_lock(exclusive=True):
        _recover_interrupted_install(artifact)
        return _uninstall_managed_app_locked(artifact)


def _uninstall_managed_app_locked(artifact: GwsReleaseArtifact) -> dict[str, Any]:
    manifest = _read_manifest(optional=True)
    if manifest is None:
        return {
            "schema": MANAGER_SCHEMA,
            "action": "uninstall",
            "status": "not_installed",
            "managed": False,
        }
    records = _validate_manifest(manifest, artifact=artifact)
    targets = _managed_targets()
    preserved: dict[str, dict[str, Any]] = {}
    removed: list[str] = []
    quarantined: list[str] = []
    for component, record in records.items():
        path = targets[component]
        if not path.exists() and not path.is_symlink():
            removed.append(component)
            continue
        if not _file_matches_record(path, record):
            if _quarantine_modified_component(component=component, path=path):
                quarantined.append(component)
            else:
                preserved[component] = record
            continue
        path.unlink()
        removed.append(component)
        if component.startswith("skill:"):
            with contextlib.suppress(OSError):
                path.parent.rmdir()
    if preserved:
        manifest["components"] = preserved
        manifest["state"] = "partially_uninstalled"
        _atomic_write_manifest(manifest)
    else:
        _unlink_safe_manifest()
    return {
        "schema": MANAGER_SCHEMA,
        "action": "uninstall",
        "status": "partially_uninstalled" if preserved else "uninstalled",
        "managed": bool(preserved),
        "removed_components": sorted(removed),
        "quarantined_modified_components": sorted(quarantined),
        "preserved_modified_components": sorted(preserved),
        "message": (
            "Tinyhat removed unchanged managed files and moved modified managed files "
            "out of active skill paths into root-only quarantine. Unmanaged files were "
            "preserved."
        ),
    }


def _quarantine_modified_component(*, component: str, path: Path) -> bool:
    """Preserve modified managed bytes without leaving active prompt files discoverable."""
    try:
        info = path.lstat()
        if info.st_uid != os.geteuid() or info.st_nlink != 1:
            return False
        QUARANTINE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        _verify_managed_directory(QUARANTINE_DIR, mode=0o700)
        safe_name = component.replace(":", "--")
        quarantine_path = QUARANTINE_DIR / f"{safe_name}-{time.time_ns()}"
        os.replace(path, quarantine_path)
        if not quarantine_path.is_symlink():
            quarantine_path.chmod(0o600)
        _fsync_directory(QUARANTINE_DIR)
        _fsync_directory(path.parent)
        if component.startswith("skill:"):
            with contextlib.suppress(OSError):
                path.parent.rmdir()
        return True
    except OSError:
        return False


@contextlib.contextmanager
def verified_managed_gws_binary() -> Iterator[ManagedGwsBinary]:
    """Yield an O_NOFOLLOW executable fd while holding the shared manager lock."""
    artifact = _require_supported_host()
    with managed_app_lock(exclusive=False):
        manifest = _read_manifest(optional=False)
        records = _validate_manifest(manifest, artifact=artifact)
        targets = _managed_targets()
        if any(
            not _file_matches_record(targets[component], record)
            for component, record in records.items()
        ):
            raise GoogleWorkspaceAppManagerError(
                "app_unavailable",
                "The managed gws app or an operation skill failed integrity checks.",
            )
        record = records.get("gws")
        if record is None:
            raise GoogleWorkspaceAppManagerError(
                "app_unavailable", "The managed gws binary is not installed."
            )
        try:
            source_fd = os.open(
                BINARY_PATH,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
        except OSError as exc:
            raise GoogleWorkspaceAppManagerError(
                "app_unavailable", "The managed gws binary could not be opened safely."
            ) from exc
        try:
            info = os.fstat(source_fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != ROOT_EXECUTABLE_MODE
                or info.st_size > MAX_BINARY_BYTES
            ):
                raise GoogleWorkspaceAppManagerError(
                    "app_unavailable",
                    "The managed gws binary is missing or failed its integrity check.",
                )
            sealed_fd = _sealed_executable_copy(
                source_fd,
                expected_sha256=record["sha256"],
            )
            proc_path = f"/proc/self/fd/{sealed_fd}"
            if not Path(proc_path).exists():
                os.close(sealed_fd)
                raise GoogleWorkspaceAppManagerError(
                    "app_unavailable", "The managed executable fd is unavailable."
                )
            try:
                yield ManagedGwsBinary(
                    fd=sealed_fd,
                    proc_path=proc_path,
                    sha256=record["sha256"],
                )
            finally:
                os.close(sealed_fd)
        finally:
            os.close(source_fd)


def _sealed_executable_copy(source_fd: int, *, expected_sha256: str) -> int:
    """Copy verified bytes into a sealed anonymous executable inode."""
    required = ("memfd_create", "MFD_ALLOW_SEALING")
    if any(not hasattr(os, name) for name in required) or not hasattr(fcntl, "F_ADD_SEALS"):
        raise GoogleWorkspaceAppManagerError(
            "app_unavailable", "This Linux host cannot seal the managed gws executable."
        )
    sealed_fd = os.memfd_create(  # type: ignore[attr-defined]
        "tinyhat-gws-v0.22.5",
        flags=os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING,  # type: ignore[attr-defined]
    )
    digest = hashlib.sha256()
    try:
        os.lseek(source_fd, 0, os.SEEK_SET)
        while chunk := os.read(source_fd, 64 * 1024):
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(sealed_fd, view)
                if written <= 0:
                    raise OSError("short memfd write")
                view = view[written:]
        if digest.hexdigest() != expected_sha256:
            raise GoogleWorkspaceAppManagerError(
                "app_unavailable", "The managed gws binary failed its integrity check."
            )
        os.fchmod(sealed_fd, 0o755)
        seals = (
            fcntl.F_SEAL_SEAL
            | fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_WRITE
        )
        fcntl.fcntl(sealed_fd, fcntl.F_ADD_SEALS, seals)
        os.lseek(sealed_fd, 0, os.SEEK_SET)
        return sealed_fd
    except Exception:
        os.close(sealed_fd)
        raise


def _download_bytes(url: str, *, max_bytes: int) -> bytes:
    _validate_download_url(url)
    opener = request.build_opener(_HttpsOnlyRedirectHandler())
    req = request.Request(url, headers={"User-Agent": "tinyhat-gws-manager/1"})
    try:
        with opener.open(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            _validate_download_url(response.geturl())
            raw_length = response.headers.get("Content-Length")
            if raw_length and int(raw_length) > max_bytes:
                raise GoogleWorkspaceAppManagerError(
                    "download_too_large", "A managed Google Workspace download was too large."
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(min(64 * 1024, max_bytes - total + 1))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise GoogleWorkspaceAppManagerError(
                        "download_too_large",
                        "A managed Google Workspace download was too large.",
                    )
            return b"".join(chunks)
    except GoogleWorkspaceAppManagerError:
        raise
    except Exception as exc:
        raise GoogleWorkspaceAppManagerError(
            "download_failed", "A pinned Google Workspace component could not be downloaded."
        ) from exc


def _validate_download_url(url: str) -> None:
    parsed = parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise GoogleWorkspaceAppManagerError(
            "unsafe_download", "A managed Google Workspace download URL was rejected."
        )


def _require_sha256(content: bytes, expected: str, *, label: str) -> None:
    if not hashlib.sha256(content).hexdigest() == expected:
        raise GoogleWorkspaceAppManagerError(
            "integrity_mismatch", f"The pinned {label} failed its integrity check."
        )


def _extract_gws_binary(archive: bytes) -> bytes:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            binary_member: tarfile.TarInfo | None = None
            for member in bundle.getmembers():
                path = PurePosixPath(member.name)
                parts = tuple(part for part in path.parts if part not in {"", "."})
                if path.is_absolute() or ".." in parts:
                    raise GoogleWorkspaceAppManagerError(
                        "unsafe_archive", "The gws release archive contained an unsafe path."
                    )
                if not (member.isdir() or member.isfile()):
                    raise GoogleWorkspaceAppManagerError(
                        "unsafe_archive", "The gws release archive contained an unsafe entry."
                    )
                if member.size < 0 or member.size > MAX_BINARY_BYTES:
                    raise GoogleWorkspaceAppManagerError(
                        "unsafe_archive", "The gws release archive contained an oversized entry."
                    )
                if parts == ("gws",):
                    if not member.isfile() or binary_member is not None:
                        raise GoogleWorkspaceAppManagerError(
                            "unsafe_archive", "The gws release archive layout was invalid."
                        )
                    binary_member = member
            if binary_member is None:
                raise GoogleWorkspaceAppManagerError(
                    "unsafe_archive", "The gws release archive did not contain its binary."
                )
            handle = bundle.extractfile(binary_member)
            if handle is None:
                raise GoogleWorkspaceAppManagerError(
                    "unsafe_archive", "The gws release binary could not be read."
                )
            binary = handle.read(MAX_BINARY_BYTES + 1)
            if len(binary) > MAX_BINARY_BYTES or len(binary) != binary_member.size:
                raise GoogleWorkspaceAppManagerError(
                    "unsafe_archive", "The gws release binary size was invalid."
                )
            return binary
    except GoogleWorkspaceAppManagerError:
        raise
    except (tarfile.TarError, OSError) as exc:
        raise GoogleWorkspaceAppManagerError(
            "unsafe_archive", "The gws release archive was invalid."
        ) from exc


def _recover_interrupted_install(artifact: GwsReleaseArtifact) -> None:
    """Recover only exact pinned artifacts left by an interrupted transaction."""
    expected = _expected_manifest_records(artifact=artifact)
    _restore_manifest_backup_if_needed(artifact)
    manifest = _read_manifest(optional=True)
    if manifest is None:
        if _adopt_complete_staged_manifest(artifact):
            manifest = _read_manifest(optional=False)
        else:
            # A first install can die after replacing one or more exact pinned
            # files but before the manifest commit. Remove only byte-for-byte
            # expected orphans; unmanaged/modified paths remain untouched and
            # will make preflight fail closed.
            for _component, record in expected.items():
                target = Path(record["path"])
                if _file_matches_record(target, record):
                    target.unlink()
                _remove_matching_transaction_files(target, record)
            _remove_valid_manifest_stages(artifact)
            return

    records = _validate_manifest(manifest, artifact=artifact)
    for _component, record in records.items():
        target = Path(record["path"])
        backups = _transaction_files(target, "backup")
        matching_backups = [path for path in backups if _file_matches_record(path, record)]
        if not target.exists() and not target.is_symlink() and matching_backups:
            os.replace(matching_backups.pop(0), target)
        if _file_matches_record(target, record):
            for backup in matching_backups:
                backup.unlink()
            _remove_matching_transaction_files(target, record, kind="stage")
    _remove_valid_manifest_stages(artifact)
    for backup in _transaction_files(MANIFEST_PATH, "backup"):
        if _manifest_candidate_is_valid(backup, artifact):
            backup.unlink()


def _restore_manifest_backup_if_needed(artifact: GwsReleaseArtifact) -> None:
    if MANIFEST_PATH.exists() or MANIFEST_PATH.is_symlink():
        return
    for backup in _transaction_files(MANIFEST_PATH, "backup"):
        if _manifest_candidate_is_valid(backup, artifact):
            os.replace(backup, MANIFEST_PATH)
            _fsync_directory(STATE_DIR)
            return


def _adopt_complete_staged_manifest(artifact: GwsReleaseArtifact) -> bool:
    for staged in _transaction_files(MANIFEST_PATH, "stage"):
        value = _read_manifest_candidate(staged)
        if value is None:
            continue
        try:
            records = _validate_manifest(value, artifact=artifact)
        except GoogleWorkspaceAppManagerError:
            continue
        if all(
            _file_matches_record(Path(record["path"]), record)
            for record in records.values()
        ):
            os.replace(staged, MANIFEST_PATH)
            _fsync_directory(STATE_DIR)
            return True
    return False


def _remove_valid_manifest_stages(artifact: GwsReleaseArtifact) -> None:
    for staged in _transaction_files(MANIFEST_PATH, "stage"):
        value = _read_manifest_candidate(staged)
        if value is None:
            continue
        try:
            _validate_manifest(value, artifact=artifact)
        except GoogleWorkspaceAppManagerError:
            continue
        staged.unlink()


def _transaction_files(target: Path, kind: str) -> list[Path]:
    prefix = f".{target.name}.tinyhat-{kind}-"
    try:
        return sorted(
            path
            for path in target.parent.iterdir()
            if path.name.startswith(prefix)
        )
    except OSError:
        return []


def _remove_matching_transaction_files(
    target: Path,
    record: dict[str, Any],
    *,
    kind: str | None = None,
) -> None:
    kinds = (kind,) if kind is not None else ("stage", "backup")
    for transaction_kind in kinds:
        for path in _transaction_files(target, transaction_kind):
            if _file_matches_record(path, record):
                path.unlink()


def _manifest_candidate_is_valid(path: Path, artifact: GwsReleaseArtifact) -> bool:
    value = _read_manifest_candidate(path)
    if value is None:
        return False
    try:
        _validate_manifest(value, artifact=artifact)
    except GoogleWorkspaceAppManagerError:
        return False
    return True


def _read_manifest_candidate(path: Path) -> dict[str, Any] | None:
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_size > MAX_MANIFEST_BYTES
        ):
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _preflight_install(
    payloads: list[ManagedPayload],
    existing_records: dict[str, dict[str, Any]],
) -> None:
    payload_map = {item.component: item for item in payloads}
    for component, record in existing_records.items():
        if component not in payload_map:
            raise GoogleWorkspaceAppManagerError(
                "managed_state_invalid", "The managed gws manifest is incompatible."
            )
        path = payload_map[component].path
        if (path.exists() or path.is_symlink()) and not _file_matches_record(path, record):
            raise GoogleWorkspaceAppManagerError(
                "modified_component",
                "A managed Google Workspace component was modified; Tinyhat preserved it.",
            )
    for item in payloads:
        if (
            item.component not in existing_records
            and (item.path.exists() or item.path.is_symlink())
        ):
            raise GoogleWorkspaceAppManagerError(
                "unmanaged_component",
                "An unmanaged file already occupies a Google Workspace install path.",
            )


def _transactional_install(  # noqa: PLR0912
    payloads: list[ManagedPayload],
    manifest: dict[str, Any],
) -> None:
    created_dirs: list[Path] = []
    staged: list[tuple[Path, Path]] = []
    committed: list[tuple[Path, Path | None]] = []
    try:
        for directory, mode in _required_directories(payloads):
            if not directory.exists():
                directory.mkdir(mode=mode, parents=True, exist_ok=True)
                created_dirs.append(directory)
            _verify_managed_directory(directory, mode=mode)
        for item in payloads:
            staged.append((item.path, _stage_file(item.path, item.content, item.mode)))
        manifest_bytes = (
            json.dumps(manifest, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8")
        staged.append((MANIFEST_PATH, _stage_file(MANIFEST_PATH, manifest_bytes, 0o600)))
        for target, temporary in staged:
            backup: Path | None = None
            if target.exists() or target.is_symlink():
                backup = target.parent / f".{target.name}.tinyhat-backup-{os.getpid()}"
                backup.unlink(missing_ok=True)
                os.replace(target, backup)
            try:
                os.replace(temporary, target)
            except Exception:
                if backup is not None and backup.exists():
                    os.replace(backup, target)
                raise
            committed.append((target, backup))
            _fsync_directory(target.parent)
        for _target, backup in committed:
            if backup is not None:
                backup.unlink(missing_ok=True)
    except Exception as exc:
        for target, backup in reversed(committed):
            with contextlib.suppress(OSError):
                target.unlink(missing_ok=True)
            if backup is not None and backup.exists():
                with contextlib.suppress(OSError):
                    os.replace(backup, target)
        for _target, temporary in staged:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
        for directory in reversed(created_dirs):
            with contextlib.suppress(OSError):
                directory.rmdir()
        if isinstance(exc, GoogleWorkspaceAppManagerError):
            raise
        raise GoogleWorkspaceAppManagerError(
            "install_failed", "The managed gws install did not complete; prior files were restored."
        ) from exc


def _required_directories(payloads: list[ManagedPayload]) -> list[tuple[Path, int]]:
    result: list[tuple[Path, int]] = []
    seen: set[Path] = set()
    for directory, mode in [
        (INSTALL_ROOT, 0o755),
        (BINARY_PATH.parent, 0o755),
        (STATE_DIR, 0o700),
        (HERMES_SKILLS_ROOT, 0o755),
        *[(item.path.parent, 0o755) for item in payloads if item.component.startswith("skill:")],
    ]:
        if directory not in seen:
            result.append((directory, mode))
            seen.add(directory)
    return result


def _verify_managed_directory(path: Path, *, mode: int) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise GoogleWorkspaceAppManagerError(
            "unsafe_path", "A managed Google Workspace directory is unavailable."
        ) from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise GoogleWorkspaceAppManagerError(
            "unsafe_path", "A managed Google Workspace directory is unsafe."
        )
    path.chmod(mode)


def _stage_file(target: Path, content: bytes, mode: int) -> Path:
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.tinyhat-stage-", dir=target.parent)
    temporary = Path(name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except Exception:
        with contextlib.suppress(OSError):
            os.close(fd)
        temporary.unlink(missing_ok=True)
        raise


def _atomic_write_manifest(manifest: dict[str, Any]) -> None:
    _verify_managed_directory(STATE_DIR, mode=0o700)
    content = (json.dumps(manifest, separators=(",", ":"), sort_keys=True) + "\n").encode()
    temporary = _stage_file(MANIFEST_PATH, content, 0o600)
    try:
        os.replace(temporary, MANIFEST_PATH)
        _fsync_directory(STATE_DIR)
    finally:
        temporary.unlink(missing_ok=True)


def _read_manifest(*, optional: bool) -> dict[str, Any] | None:
    if not MANIFEST_PATH.exists() and not MANIFEST_PATH.is_symlink():
        if optional:
            return None
        raise GoogleWorkspaceAppManagerError(
            "app_unavailable", "The managed gws app is not installed."
        )
    try:
        info = MANIFEST_PATH.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_size > MAX_MANIFEST_BYTES
        ):
            raise OSError("unsafe manifest")
        fd = os.open(MANIFEST_PATH, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise GoogleWorkspaceAppManagerError(
            "managed_state_invalid", "The managed gws manifest failed validation."
        ) from exc
    if not isinstance(value, dict):
        raise GoogleWorkspaceAppManagerError(
            "managed_state_invalid", "The managed gws manifest failed validation."
        )
    return value


def _validate_manifest(
    value: dict[str, Any] | None,
    *,
    artifact: GwsReleaseArtifact,
) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    version = value.get("version")
    release = TRUSTED_MANAGED_RELEASES.get(str(version))
    if not isinstance(release, dict):
        raise GoogleWorkspaceAppManagerError(
            "managed_state_invalid", "The managed gws manifest version is not trusted."
        )
    artifacts = release.get("artifacts")
    if not isinstance(artifacts, dict):
        raise GoogleWorkspaceAppManagerError(
            "managed_state_invalid", "The managed gws release record is invalid."
        )
    manifest_artifact = artifacts.get(str(value.get("architecture")))
    if not isinstance(manifest_artifact, GwsReleaseArtifact):
        raise GoogleWorkspaceAppManagerError(
            "managed_state_invalid", "The managed gws manifest architecture is not trusted."
        )
    if (
        value.get("schema") != MANIFEST_SCHEMA
        or value.get("platform") != "linux"
        or value.get("architecture") != artifact.architecture
        or value.get("archive_sha256") != manifest_artifact.archive_sha256
        or not isinstance(value.get("components"), dict)
    ):
        raise GoogleWorkspaceAppManagerError(
            "managed_state_invalid", "The managed gws manifest is incompatible."
        )
    targets = _managed_targets()
    expected_records = _expected_manifest_records_for_release(
        version=str(version),
        artifact=manifest_artifact,
        release=release,
    )
    component_names = set(value["components"])
    is_partial = value.get("state") == "partially_uninstalled"
    if (not is_partial and component_names != set(expected_records)) or (
        is_partial and not component_names.issubset(expected_records)
    ):
        raise GoogleWorkspaceAppManagerError(
            "managed_state_invalid", "The managed gws manifest is incomplete."
        )
    records: dict[str, dict[str, Any]] = {}
    for component, raw_record in value["components"].items():
        if component not in targets or not isinstance(raw_record, dict):
            raise GoogleWorkspaceAppManagerError(
                "managed_state_invalid", "The managed gws manifest contains an unsafe entry."
            )
        expected_record = expected_records[component]
        if raw_record != expected_record:
            raise GoogleWorkspaceAppManagerError(
                "managed_state_invalid", "The managed gws manifest contains an unsafe entry."
            )
        records[component] = dict(raw_record)
    return records


def _expected_manifest_records(
    *,
    artifact: GwsReleaseArtifact,
) -> dict[str, dict[str, Any]]:
    release = TRUSTED_MANAGED_RELEASES.get(PINNED_GWS_VERSION)
    if not isinstance(release, dict):
        raise GoogleWorkspaceAppManagerError(
            "package_invalid", "The current managed gws release is not trusted."
        )
    return _expected_manifest_records_for_release(
        version=PINNED_GWS_VERSION,
        artifact=artifact,
        release=release,
    )


def _expected_manifest_records_for_release(
    *,
    version: str,
    artifact: GwsReleaseArtifact,
    release: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    targets = _managed_targets()
    records: dict[str, dict[str, Any]] = {
        "gws": {
            "path": str(targets["gws"]),
            "sha256": artifact.binary_sha256,
            "mode": 0o755,
            "source": artifact.archive_url,
        }
    }
    skills = release.get("skills")
    shared_sha256 = release.get("shared_sha256")
    if not isinstance(skills, dict) or not isinstance(shared_sha256, str):
        raise GoogleWorkspaceAppManagerError(
            "managed_state_invalid", "The managed gws release record is invalid."
        )
    skill_base_url = (
        f"https://raw.githubusercontent.com/googleworkspace/cli/v{version}/skills"
    )
    for name, expected_hash in skills.items():
        component = f"skill:{name}"
        records[component] = {
            "path": str(targets[component]),
            "sha256": expected_hash,
            "mode": 0o644,
            "source": f"{skill_base_url}/{name}/SKILL.md",
        }
    records["skill:gws-shared"] = {
        "path": str(targets["skill:gws-shared"]),
        "sha256": shared_sha256,
        "mode": 0o644,
        "source": "tinyhat-plugin:gws-shared",
    }
    return records


def _file_matches_record(path: Path, record: dict[str, Any]) -> bool:
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != record["mode"]
        ):
            return False
        if info.st_size > MAX_MANAGED_COMPONENT_BYTES:
            return False
        digest_builder = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(64 * 1024):
                digest_builder.update(chunk)
        digest = digest_builder.hexdigest()
    except OSError:
        return False
    return digest == record["sha256"]


def _unlink_safe_manifest() -> None:
    manifest = _read_manifest(optional=False)
    _ = manifest
    MANIFEST_PATH.unlink()
    _fsync_directory(STATE_DIR)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
