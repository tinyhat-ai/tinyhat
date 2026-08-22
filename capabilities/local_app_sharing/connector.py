"""Computer-private Cloudflare connector lifecycle for local app sharing."""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import os
import platform
import re
import signal
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from ...platform import PlatformClient, computer_api_path

CLOUDFLARED_VERSION = "2026.7.3"
CLOUDFLARED_RELEASE_BASE = (
    "https://github.com/cloudflare/cloudflared/releases/download/"
    f"{CLOUDFLARED_VERSION}"
)
ARTIFACTS = {
    ("Linux", "x86_64"): (
        "cloudflared-linux-amd64",
        "9d71c677db00134c1bd4144b7783486b654ad281b1ea62b4972098d19f770f17",
        False,
        "9d71c677db00134c1bd4144b7783486b654ad281b1ea62b4972098d19f770f17",
    ),
    ("Linux", "aarch64"): (
        "cloudflared-linux-arm64",
        "65259e652a7bea08bf5df603233ab22b8bf3116af8df9f9206209af6a1b955c0",
        False,
        "65259e652a7bea08bf5df603233ab22b8bf3116af8df9f9206209af6a1b955c0",
    ),
    ("Darwin", "x86_64"): (
        "cloudflared-darwin-amd64.tgz",
        "70d1c8684fa6d14b5843787ec8d1ea8e18b23650e424f4ea43d849a506487c3b",
        True,
        "e88fe5874d42a94f49a7ea59cabc3722d2962d0449232b0f3b1a426a712e275c",
    ),
    ("Darwin", "arm64"): (
        "cloudflared-darwin-arm64.tgz",
        "90c5a4f914d705fd70c135dba6d80b1791d254b08d6d4136301941f88330dd09",
        True,
        "f35c50089cd25f77a4cb5a2152036bc26db15aa31fbe11f7995d2e42a4ed6257",
    ),
}
HOSTNAME_RE = re.compile(
    r"^c-[0-9a-f]{24}\.(?:viewd|view)\.tinyhat\.ai$",
    re.IGNORECASE,
)
CONNECTOR_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/=]{80,4096}$")
STATE_DIR = Path.home() / ".tinyhat" / "local-app-sharing"
BINARY_PATH = STATE_DIR / f"cloudflared-{CLOUDFLARED_VERSION}"
TOKEN_PATH = STATE_DIR / "cloudflared.token"
PID_PATH = STATE_DIR / "cloudflared.pid"
LOG_PATH = STATE_DIR / "cloudflared.log"
LOCK_PATH = STATE_DIR / "cloudflared.lock"
DOWNLOAD_LIMIT_BYTES = 100 * 1024 * 1024
CONNECTOR_METRICS_URL = "http://127.0.0.1:9322/ready"
CONNECTOR_GRACE_SECONDS = 5
CONNECTOR_STOP_POLL_SECONDS = 0.1
CONNECTOR_STOP_POLLS = 60
CONNECTOR_KILL_POLLS = 20
CONNECTOR_READY_POLL_SECONDS = 0.25
CONNECTOR_READY_POLLS = 80


def _prepare_state_dir() -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)


def _artifact() -> tuple[str, str, bool, str]:
    machine = platform.machine().lower()
    if machine in {"amd64", "x64"}:
        machine = "x86_64"
    elif machine in {"arm64", "armv8"}:
        machine = "aarch64" if platform.system() == "Linux" else "arm64"
    artifact = ARTIFACTS.get((platform.system(), machine))
    if artifact is None:
        raise RuntimeError("this Computer platform is not supported by cloudflared")
    return artifact


def _download(path: Path, *, url: str) -> None:
    downloaded = 0
    try:
        with request.urlopen(url, timeout=30) as response, path.open("wb") as target:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > DOWNLOAD_LIMIT_BYTES:
                    raise RuntimeError("cloudflared download exceeded the size limit")
                target.write(chunk)
    except (error.URLError, OSError, TimeoutError) as exc:
        raise RuntimeError("could not download the pinned cloudflared connector") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _install_cloudflared() -> Path:
    """Install only the pinned, checksum-verified official release asset."""

    asset_name, expected_sha256, compressed, binary_sha256 = _artifact()
    if (
        BINARY_PATH.is_file()
        and os.access(BINARY_PATH, os.X_OK)
        and hmac.compare_digest(_sha256(BINARY_PATH), binary_sha256)
    ):
        return BINARY_PATH
    _prepare_state_dir()
    artifact_file = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix="cloudflared-artifact-",
        dir=STATE_DIR,
        delete=False,
    )
    artifact_path = Path(artifact_file.name)
    artifact_file.close()
    binary_file = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix="cloudflared-binary-",
        dir=STATE_DIR,
        delete=False,
    )
    binary_path = Path(binary_file.name)
    binary_file.close()
    try:
        _download(artifact_path, url=f"{CLOUDFLARED_RELEASE_BASE}/{asset_name}")
        if not hmac.compare_digest(_sha256(artifact_path), expected_sha256):
            raise RuntimeError("cloudflared release checksum verification failed")
        if compressed:
            with tarfile.open(artifact_path, mode="r:gz") as archive:
                members = [member for member in archive.getmembers() if member.name == "cloudflared"]
                if len(members) != 1 or not members[0].isfile():
                    raise RuntimeError("cloudflared release archive is invalid")
                source = archive.extractfile(members[0])
                if source is None:
                    raise RuntimeError("cloudflared release archive is invalid")
                with binary_path.open("wb") as target:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        target.write(chunk)
        else:
            os.replace(artifact_path, binary_path)
        if not hmac.compare_digest(_sha256(binary_path), binary_sha256):
            raise RuntimeError("cloudflared binary checksum verification failed")
        os.chmod(binary_path, 0o700)
        os.replace(binary_path, BINARY_PATH)
    finally:
        artifact_path.unlink(missing_ok=True)
        binary_path.unlink(missing_ok=True)
    return BINARY_PATH


def _validated_connector_payload(payload: dict[str, Any]) -> tuple[str, str]:
    hostname = str(payload.get("hostname") or "").strip().lower()
    public_origin = str(payload.get("public_origin") or "").strip().lower()
    token = str(payload.get("connector_token") or "").strip()
    if (
        payload.get("schema_version") != "v1"
        or HOSTNAME_RE.fullmatch(hostname) is None
        or public_origin != f"https://{hostname}"
        or CONNECTOR_TOKEN_RE.fullmatch(token) is None
    ):
        raise ValueError("platform returned invalid Computer viewer connector material")
    return public_origin, token


def _write_token(token: str) -> bool:
    """Persist the connector token atomically; return whether it changed."""

    try:
        existing = TOKEN_PATH.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        existing = ""
    changed = not hmac.compare_digest(existing, token)
    if not changed:
        os.chmod(TOKEN_PATH, 0o600)
        return False
    token_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="ascii",
        prefix="cloudflared-token-",
        dir=STATE_DIR,
        delete=False,
    )
    token_path = Path(token_file.name)
    try:
        token_file.write(f"{token}\n")
        token_file.flush()
        os.fsync(token_file.fileno())
        token_file.close()
        os.chmod(token_path, 0o600)
        os.replace(token_path, TOKEN_PATH)
    finally:
        if not token_file.closed:
            token_file.close()
        token_path.unlink(missing_ok=True)
    return True


def _connector_process() -> subprocess.CompletedProcess[str] | None:
    try:
        pid = int(PID_PATH.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    if pid <= 1:
        return None
    try:
        process = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if process.returncode != 0:
        return None
    command = process.stdout
    if (
        "cloudflared-" not in command
        or "tunnel" not in command
        or "--token-file" not in command
        or str(TOKEN_PATH) not in command
    ):
        return None
    return process


def _stop_connector() -> None:
    if _connector_process() is None:
        return
    pid = int(PID_PATH.read_text(encoding="ascii").strip())
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(CONNECTOR_STOP_POLLS):
        if _connector_process() is None:
            return
        time.sleep(CONNECTOR_STOP_POLL_SECONDS)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    for _ in range(CONNECTOR_KILL_POLLS):
        if _connector_process() is None:
            return
        time.sleep(CONNECTOR_STOP_POLL_SECONDS)
    raise RuntimeError("the prior Computer viewer connector could not be stopped")


def _connector_ready() -> bool:
    try:
        with request.urlopen(CONNECTOR_METRICS_URL, timeout=0.5) as response:
            return response.status == 200
    except (error.HTTPError, error.URLError, OSError, TimeoutError):
        return False


def _start_connector(binary_path: Path) -> None:
    with LOG_PATH.open("ab", buffering=0) as log_file:
        os.chmod(LOG_PATH, 0o600)
        process = subprocess.Popen(
            [
                str(binary_path),
                "tunnel",
                "--no-autoupdate",
                "--metrics",
                "127.0.0.1:9322",
                "--grace-period",
                f"{CONNECTOR_GRACE_SECONDS}s",
                "run",
                "--token-file",
                str(TOKEN_PATH),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    PID_PATH.write_text(f"{process.pid}\n", encoding="ascii")
    os.chmod(PID_PATH, 0o600)
    for _ in range(CONNECTOR_READY_POLLS):
        if process.poll() is not None:
            raise RuntimeError("the Computer viewer connector exited during startup")
        if _connector_ready():
            return
        time.sleep(CONNECTOR_READY_POLL_SECONDS)
    _stop_connector()
    raise RuntimeError("the Computer viewer connector did not become ready")


def ensure_connector_running(
    *,
    client: PlatformClient,
    platform_auth: str,
) -> str:
    """Provision and run this Computer's tunnel without exposing its token."""

    _prepare_state_dir()
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        os.chmod(LOCK_PATH, 0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        # Keep token retrieval, persistence, and process restart in one local
        # critical section so concurrent share requests cannot apply responses
        # out of order. The platform returns a stable token for the lifetime of
        # the remotely managed tunnel and rotates it only by recreating it.
        response = client.post_json(
            computer_api_path(platform_auth, "viewer-tunnel/v1/ensure"),
            {},
        )
        public_origin, token = _validated_connector_payload(response)
        token_changed = _write_token(token)
        if token_changed:
            _stop_connector()
        if _connector_process() is None:
            _start_connector(_install_cloudflared())
    return public_origin


__all__ = ["CLOUDFLARED_VERSION", "ensure_connector_running"]
