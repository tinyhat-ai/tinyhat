"""Tinyhat platform client for plugin capabilities.

The runtime provides the Computer identity and environment. Plugin tools use
that identity to call versioned platform APIs, but they do not mint tokens or
carry private platform URLs in skills.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import time
from pathlib import Path
from typing import Any
from urllib import error, parse, request

DEFAULT_ENV_FILES = (
    Path("/opt/tinyhat-hermes-runtime/env/runtime.env"),
    Path("/etc/tinyhat/hermes-runtime.env"),
)


class PlatformError(RuntimeError):
    """The Tinyhat platform request failed."""


class CachedGoogleIdentityToken:
    """Fetch and cache the VM identity token used for platform calls."""

    def __init__(self, *, audience: str, timeout_seconds: int = 5) -> None:
        self.audience = audience.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._token: str | None = None
        self._expires_at = 0

    def __call__(self) -> str:
        now = int(time.time())
        if self._token and self._expires_at - 60 > now:
            return self._token
        token = self._fetch()
        self._token = token
        self._expires_at = _jwt_exp(token) or (now + 300)
        return token

    def _fetch(self) -> str:
        query = parse.urlencode({"audience": self.audience, "format": "full"})
        req = request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/"
            f"service-accounts/default/identity?{query}",
            headers={"Metadata-Flavor": "Google"},
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                return response.read().decode("utf-8").strip()
        except error.URLError as exc:
            raise PlatformError(
                f"failed to fetch Google identity token: {exc.reason}"
            ) from exc


class PlatformClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        token_provider: Any | None = None,
        timeout_seconds: int = 20,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.token_provider = token_provider
        self.timeout_seconds = timeout_seconds

    def get_json(self, path: str) -> dict[str, Any]:
        return self._request_json("GET", path, None)

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", path, payload)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        token = self.token_provider() if self.token_provider else self.token
        if not token:
            raise PlatformError("missing platform authentication token")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "tinyhat-plugin/0.20",
        }
        body = (
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
            if payload is not None
            else None
        )
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PlatformError(
                f"{method} {path} failed with HTTP {exc.code}: {detail}"
            ) from exc
        except error.URLError as exc:
            raise PlatformError(f"{method} {path} failed: {exc.reason}") from exc
        if not raw:
            return {}
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise PlatformError(f"{method} {path} returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise PlatformError(f"{method} {path} returned non-object JSON")
        return decoded


def build_platform_client(env: dict[str, str] | None = None) -> tuple[PlatformClient, str]:
    values = runtime_env(env)
    base_url = values.get("TINYHAT_PLATFORM_URL", "").strip()
    if not base_url:
        raise PlatformError("TINYHAT_PLATFORM_URL is not configured")
    local_token = values.get("TINYHAT_LOCAL_DEV_TOKEN", "").strip()
    if local_token:
        return PlatformClient(base_url=base_url, token=local_token), "local_dev"
    audience = values.get("TINYHAT_COMPUTER_TOKEN_AUDIENCE", "").strip() or base_url
    return (
        PlatformClient(
            base_url=base_url,
            token_provider=CachedGoogleIdentityToken(audience=audience),
        ),
        "gcloud",
    )


def computer_api_path(platform_auth: str, suffix: str) -> str:
    clean_suffix = suffix.lstrip("/")
    if platform_auth == "gcloud":
        return f"/hapi/v1/computers/me/{clean_suffix}"
    return f"/hapi/v1/computers/local-dev/{clean_suffix}"


def runtime_env(env: dict[str, str] | None = None) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in DEFAULT_ENV_FILES:
        values.update(_read_env_file(path))
    values.update(os.environ if env is None else env)
    return values


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        try:
            parts = shlex.split(raw_value, posix=True)
            value = parts[0] if parts else ""
        except ValueError:
            value = raw_value.strip().strip("'\"")
        values[key] = value
    return values


def _jwt_exp(token: str) -> int | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return None
    exp = decoded.get("exp") if isinstance(decoded, dict) else None
    return int(exp) if isinstance(exp, int) else None
