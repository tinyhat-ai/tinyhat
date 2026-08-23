"""Loopback-only encrypted HTTP gateway for Tinyhat local app shares."""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from ...platform import PlatformClient, PlatformError, build_platform_client, computer_api_path
from .crypto import (
    CONTENT_CIPHER,
    CONTENT_ENCRYPTION_PROTOCOL,
    KEY_AGREEMENT_ALGORITHM,
    LocalAppCryptoError,
    SessionKeyStore,
    decrypt_json,
    derive_content_key,
    encrypt_json,
    request_aad,
    response_aad,
)
from .tool import GATEWAY_HOST, GATEWAY_PORT, GATEWAY_PROTOCOL_VERSION, STATE_DIR
from .viewer import APP_SHELL, SERVICE_WORKER, VIEWER_PAGE

COOKIE_PREFIX = "__Host-tinyhat_share_"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_UPSTREAM_BODY_BYTES = 10 * 1024 * 1024
MAX_TARGET_LENGTH = 4096
MAX_ACTIVE_CONNECTIONS = 100
MAX_REQUEST_IDS_PER_CONNECTION = 4096
MAX_PORT = 65535
MAX_HEADER_VALUE_LENGTH = 4096
CONNECTION_ID_RE = re.compile(r"^e2e_[A-Za-z0-9_-]{20,80}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
SAFE_REQUEST_HEADERS = frozenset(
    {"accept", "accept-language", "if-none-match", "if-modified-since", "range"}
)
HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


def _client() -> tuple[PlatformClient, str]:
    return build_platform_client()


def _cookie_name(session_id: str) -> str:
    return f"{COOKIE_PREFIX}{session_id}"


def _browser_grant_cookie(
    session_id: str, access_token: str, *, embedded: bool
) -> str:
    """Use CHIPS only for iframe clients that need third-party cookie access.

    Native Telegram Mini Apps and ordinary browsers load the viewer as a
    top-level page. Some WebKit releases reject cookies carrying the
    ``Partitioned`` attribute there, while Telegram Web embeds the viewer and
    needs a partitioned cookie. The viewer reports that browsing-context fact;
    it does not change whether the platform authorizes the share.
    """

    cookie = (
        f"{_cookie_name(session_id)}={access_token}; "
        "Path=/; Secure; HttpOnly; SameSite=None"
    )
    return f"{cookie}; Partitioned" if embedded else cookie


def _parse_cookie(header: str | None, session_id: str) -> str | None:
    if not header:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(header)
    except Exception:
        return None
    morsel = cookie.get(_cookie_name(session_id))
    if morsel is None or re.fullmatch(r"[A-Za-z0-9_-]{32,256}", morsel.value) is None:
        return None
    return morsel.value


def _match(path: str, suffix: str = "") -> str | None:
    clean_path = urlsplit(path).path
    match = re.fullmatch(
        rf"/s/(las_[A-Za-z0-9_-]{{20,80}}){re.escape(suffix)}/?",
        clean_path,
    )
    return match.group(1) if match else None


def _app_session_from_path(path: str) -> str | None:
    clean_path = urlsplit(path).path
    match = re.match(r"^/s/(las_[A-Za-z0-9_-]{20,80})/app(?:/|$)", clean_path)
    return match.group(1) if match else None


def _expires_at_epoch(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError as exc:
        raise LocalAppCryptoError("Encrypted local app grant is invalid.") from exc


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


@dataclass
class _EncryptedConnection:
    connection_id: str
    session_id: str
    port: int
    key: bytearray
    expires_at_epoch: float
    used_request_ids: set[str] = field(default_factory=set)
    upstream_cookies: dict[str, str] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def wipe(self) -> None:
        for index in range(len(self.key)):
            self.key[index] = 0
        self.used_request_ids.clear()
        self.upstream_cookies.clear()


class _ConnectionRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, _EncryptedConnection] = {}

    def _prune_locked(self) -> None:
        now = time.time()
        expired = [key for key, item in self._items.items() if item.expires_at_epoch <= now]
        for key in expired:
            self._items.pop(key).wipe()

    def create(
        self,
        *,
        session_id: str,
        port: int,
        key: bytes,
        expires_at_epoch: float,
    ) -> _EncryptedConnection:
        with self._lock:
            self._prune_locked()
            if len(self._items) >= MAX_ACTIVE_CONNECTIONS:
                oldest = min(self._items, key=lambda value: self._items[value].expires_at_epoch)
                self._items.pop(oldest).wipe()
            connection_id = f"e2e_{secrets.token_urlsafe(24)}"
            item = _EncryptedConnection(
                connection_id=connection_id,
                session_id=session_id,
                port=port,
                key=bytearray(key),
                expires_at_epoch=expires_at_epoch,
            )
            self._items[connection_id] = item
            return item

    def reserve_request(
        self, *, connection_id: str, session_id: str, request_id: str, port: int
    ) -> _EncryptedConnection:
        with self._lock:
            self._prune_locked()
            item = self._items.get(connection_id)
            if (
                item is None
                or item.session_id != session_id
                or item.port != port
                or request_id in item.used_request_ids
            ):
                raise LocalAppCryptoError("Encrypted local app connection is invalid.")
            if len(item.used_request_ids) >= MAX_REQUEST_IDS_PER_CONNECTION:
                raise LocalAppCryptoError("Encrypted local app connection must be refreshed.")
            item.used_request_ids.add(request_id)
            return item


def _capture_upstream_cookies(
    connection: _EncryptedConnection,
    raw_headers: list[tuple[str, str]],
) -> None:
    for name, value in raw_headers:
        if name.lower() != "set-cookie":
            continue
        cookie = SimpleCookie()
        try:
            cookie.load(value)
        except Exception:
            continue
        for cookie_name, morsel in cookie.items():
            connection.upstream_cookies[cookie_name] = morsel.value


def _safe_upstream_response_headers(
    raw_headers: list[tuple[str, str]],
) -> list[list[str]]:
    safe_headers: list[list[str]] = []
    stripped = {"content-length", "set-cookie", "cache-control", "pragma"}
    for name, value in raw_headers:
        lower = name.lower()
        if lower in HOP_BY_HOP_HEADERS or lower in stripped:
            continue
        safe_value = value
        if lower == "location":
            location = urlsplit(value)
            if location.hostname in {"localhost", "127.0.0.1", "::1"}:
                safe_value = location.path or "/"
                if location.query:
                    safe_value = f"{safe_value}?{location.query}"
        safe_headers.append([name, safe_value])
    return safe_headers


def _handler(
    client_factory: Callable[[], tuple[PlatformClient, str]],
    *,
    key_store: SessionKeyStore,
    connections: _ConnectionRegistry,
) -> type[BaseHTTPRequestHandler]:
    class GatewayHandler(BaseHTTPRequestHandler):
        server_version = "TinyhatLocalAppGateway/2"

        def log_message(self, format_string: str, *args: Any) -> None:
            _ = (format_string, args)

        def _security_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")

        def _write_bytes(
            self,
            status: int,
            body: bytes,
            *,
            content_type: str,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self._security_headers()
            if extra_headers:
                for name, value in extra_headers.items():
                    self.send_header(name, value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _write_json(
            self,
            status: int,
            payload: dict[str, Any],
            *,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self._write_bytes(
                status,
                json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                content_type="application/json",
                extra_headers=extra_headers,
            )

        def _read_json(self, *, maximum_bytes: int = MAX_JSON_BYTES) -> dict[str, Any] | None:
            try:
                length = int(self.headers.get("content-length") or "0")
            except ValueError:
                return None
            if not 1 <= length <= maximum_bytes:
                return None
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8", errors="strict"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            return payload if isinstance(payload, dict) else None

        def _resolve(self, session_id: str, access_token: str) -> dict[str, Any] | None:
            try:
                client, platform_auth = client_factory()
                payload = client.post_json(
                    computer_api_path(
                        platform_auth,
                        f"local-app-shares/v1/{quote(session_id, safe='')}/resolve",
                    ),
                    {"access_token": access_token},
                )
            except PlatformError:
                return None
            if payload.get("content_encryption") != CONTENT_ENCRYPTION_PROTOCOL:
                return None
            return payload

        def _authorize(self, session_id: str, access_code: str) -> dict[str, Any] | None:
            try:
                client, platform_auth = client_factory()
                payload = client.post_json(
                    computer_api_path(
                        platform_auth,
                        f"local-app-shares/v1/{quote(session_id, safe='')}/authorize",
                    ),
                    {"access_code": access_code},
                )
            except PlatformError:
                return None
            return (
                payload
                if payload.get("content_encryption") == CONTENT_ENCRYPTION_PROTOCOL
                else None
            )

        def _authorize_link(self, session_id: str) -> dict[str, Any] | None:
            try:
                client, platform_auth = client_factory()
                payload = client.post_json(
                    computer_api_path(
                        platform_auth,
                        f"local-app-shares/v1/{quote(session_id, safe='')}/authorize-link",
                    ),
                    {},
                )
            except PlatformError:
                return None
            return (
                payload
                if payload.get("content_encryption") == CONTENT_ENCRYPTION_PROTOCOL
                else None
            )

        def _authorize_telegram(
            self, session_id: str, telegram_init_data: str
        ) -> dict[str, Any] | None:
            try:
                client, platform_auth = client_factory()
                payload = client.post_json(
                    computer_api_path(
                        platform_auth,
                        f"local-app-shares/v1/{quote(session_id, safe='')}/authorize-telegram",
                    ),
                    {"telegram_init_data": telegram_init_data},
                )
            except PlatformError:
                return None
            return (
                payload
                if payload.get("content_encryption") == CONTENT_ENCRYPTION_PROTOCOL
                else None
            )

        def _write_browser_grant(
            self,
            session_id: str,
            payload: dict[str, Any] | None,
            *,
            embedded: bool,
        ) -> None:
            token = payload.get("access_token") if isinstance(payload, dict) else None
            if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token) is None:
                self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "share_access_denied"})
                return
            self._write_json(
                HTTPStatus.OK,
                {"ok": True, "content_encryption": CONTENT_ENCRYPTION_PROTOCOL},
                extra_headers={
                    "Set-Cookie": _browser_grant_cookie(
                        session_id,
                        token,
                        embedded=embedded,
                    )
                },
            )

        def _authorized_target(self, session_id: str) -> tuple[int, float] | None:
            access_token = _parse_cookie(self.headers.get("cookie"), session_id)
            if access_token is None:
                return None
            resolved = self._resolve(session_id, access_token)
            if not isinstance(resolved, dict):
                return None
            port = resolved.get("port")
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= MAX_PORT:
                return None
            try:
                expires_at_epoch = _expires_at_epoch(resolved.get("expires_at"))
            except LocalAppCryptoError:
                return None
            if expires_at_epoch <= time.time():
                return None
            return port, expires_at_epoch

        def _write_viewer(self) -> None:
            self._write_bytes(
                HTTPStatus.OK,
                VIEWER_PAGE,
                content_type="text/html; charset=utf-8",
                extra_headers={
                    "Content-Security-Policy": (
                        "default-src 'none'; style-src 'unsafe-inline'; "
                        "script-src 'unsafe-inline' https://telegram.org; "
                        "connect-src 'self'; frame-src 'self'; worker-src 'self'; "
                        "form-action 'none'; frame-ancestors https://web.telegram.org "
                        "https://*.telegram.org; base-uri 'none'"
                    )
                },
            )

        def _write_service_worker(self) -> None:
            self._write_bytes(
                HTTPStatus.OK,
                SERVICE_WORKER,
                content_type="text/javascript; charset=utf-8",
                extra_headers={"Service-Worker-Allowed": "/"},
            )

        def _write_app_shell(self) -> None:
            self._write_bytes(
                HTTPStatus.OK,
                APP_SHELL,
                content_type="text/javascript; charset=utf-8",
            )

        def _write_key(self, session_id: str) -> None:
            if self._authorized_target(session_id) is None:
                self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "share_access_required"})
                return
            try:
                session_key = key_store.load(session_id)
            except LocalAppCryptoError:
                self._write_json(HTTPStatus.GONE, {"error": "share_key_unavailable"})
                return
            self._write_json(
                HTTPStatus.OK,
                {
                    "content_encryption": CONTENT_ENCRYPTION_PROTOCOL,
                    "key_agreement": KEY_AGREEMENT_ALGORITHM,
                    "content_cipher": CONTENT_CIPHER,
                    "public_key_jwk": session_key.public_jwk,
                    "fingerprint": session_key.fingerprint,
                },
            )

        def _handshake(self, session_id: str) -> None:
            target = self._authorized_target(session_id)
            payload = self._read_json(maximum_bytes=8192)
            if target is None or payload is None:
                self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "share_access_required"})
                return
            public_jwk = payload.get("browser_public_jwk")
            if not isinstance(public_jwk, dict):
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_browser_key"})
                return
            try:
                session_key = key_store.load(session_id)
                salt = os.urandom(32)
                content_key = derive_content_key(
                    session_key=session_key,
                    browser_public_jwk=public_jwk,
                    salt=salt,
                )
            except LocalAppCryptoError:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_browser_key"})
                return
            port, grant_expiry = target
            connection = connections.create(
                session_id=session_id,
                port=port,
                key=content_key,
                expires_at_epoch=min(grant_expiry, session_key.expires_at_epoch),
            )
            self._write_json(
                HTTPStatus.OK,
                {
                    "content_encryption": CONTENT_ENCRYPTION_PROTOCOL,
                    "connection_id": connection.connection_id,
                    "salt": _b64url(salt),
                    "expires_at_epoch": connection.expires_at_epoch,
                },
            )

        def _upstream_request(
            self,
            *,
            connection: _EncryptedConnection,
            method: str,
            target: str,
            request_headers: dict[str, str],
        ) -> dict[str, Any]:
            headers = {
                name.title(): value
                for name, value in request_headers.items()
                if name in SAFE_REQUEST_HEADERS and len(value) <= MAX_HEADER_VALUE_LENGTH
            }
            headers["Host"] = f"127.0.0.1:{connection.port}"
            headers["Accept-Encoding"] = "identity"
            with connection.lock:
                if connection.upstream_cookies:
                    headers["Cookie"] = "; ".join(
                        f"{name}={value}" for name, value in connection.upstream_cookies.items()
                    )
                upstream = http.client.HTTPConnection("127.0.0.1", connection.port, timeout=15)
                try:
                    upstream.request(method, target, headers=headers)
                    response = upstream.getresponse()
                    body = response.read(MAX_UPSTREAM_BODY_BYTES + 1)
                    if len(body) > MAX_UPSTREAM_BODY_BYTES:
                        raise LocalAppCryptoError("Local app response is too large.")
                    raw_headers = response.getheaders()
                    status = response.status
                    reason = response.reason
                except OSError as exc:
                    raise LocalAppCryptoError("Local app is unavailable.") from exc
                finally:
                    upstream.close()
                _capture_upstream_cookies(connection, raw_headers)
            return {
                "status": status,
                "reason": reason or "",
                "headers": _safe_upstream_response_headers(raw_headers),
                "body": _b64url(body),
            }

        def _encrypted_request(self, session_id: str) -> None:
            target = self._authorized_target(session_id)
            outer = self._read_json()
            if target is None or outer is None:
                self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "share_access_required"})
                return
            connection_id = str(outer.get("connection_id") or "")
            request_id = str(outer.get("request_id") or "")
            if (
                outer.get("content_encryption") != CONTENT_ENCRYPTION_PROTOCOL
                or CONNECTION_ID_RE.fullmatch(connection_id) is None
                or REQUEST_ID_RE.fullmatch(request_id) is None
            ):
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_encrypted_request"})
                return
            port, _ = target
            try:
                connection = connections.reserve_request(
                    connection_id=connection_id,
                    session_id=session_id,
                    request_id=request_id,
                    port=port,
                )
                request_payload = decrypt_json(
                    key=bytes(connection.key),
                    nonce=str(outer.get("nonce") or ""),
                    ciphertext=str(outer.get("ciphertext") or ""),
                    aad=request_aad(
                        session_id=session_id,
                        connection_id=connection_id,
                        request_id=request_id,
                    ),
                )
                method = str(request_payload.get("method") or "").upper()
                raw_target = str(request_payload.get("target") or "")
                parsed_target = urlsplit(raw_target)
                headers_payload = request_payload.get("headers")
                if (
                    method not in {"GET", "HEAD"}
                    or not raw_target.startswith("/")
                    or len(raw_target) > MAX_TARGET_LENGTH
                    or parsed_target.scheme
                    or parsed_target.netloc
                    or not isinstance(headers_payload, dict)
                ):
                    raise LocalAppCryptoError("Encrypted local app request is invalid.")
                request_headers = {
                    str(name).lower(): str(value)
                    for name, value in headers_payload.items()
                    if isinstance(name, str) and isinstance(value, str)
                }
                response_payload = self._upstream_request(
                    connection=connection,
                    method=method,
                    target=raw_target,
                    request_headers=request_headers,
                )
                encrypted = encrypt_json(
                    key=bytes(connection.key),
                    payload=response_payload,
                    aad=response_aad(
                        session_id=session_id,
                        connection_id=connection_id,
                        request_id=request_id,
                    ),
                )
            except LocalAppCryptoError:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_encrypted_request"})
                return
            self._write_json(
                HTTPStatus.OK,
                {"content_encryption": CONTENT_ENCRYPTION_PROTOCOL, **encrypted},
            )

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/__tinyhat_share/health":
                self._write_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "protocol_version": GATEWAY_PROTOCOL_VERSION,
                        "content_encryption": CONTENT_ENCRYPTION_PROTOCOL,
                    },
                )
                return
            if path == "/__tinyhat_share/e2ee-v3-sw.js":
                self._write_service_worker()
                return
            if path == "/__tinyhat_share/app-shell-v3.js":
                self._write_app_shell()
                return
            session_id = _match(self.path)
            if session_id is not None:
                self._write_viewer()
                return
            key_session_id = _match(self.path, "/e2ee-key")
            if key_session_id is not None:
                self._write_key(key_session_id)
                return
            if _app_session_from_path(self.path) is not None:
                self._write_json(
                    HTTPStatus.UPGRADE_REQUIRED,
                    {"error": "encrypted_transport_required"},
                )
                return
            self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "share_access_required"})

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_POST(self) -> None:
            link_session_id = _match(self.path, "/link-authorize")
            if link_session_id is not None:
                payload = self._read_json(maximum_bytes=1024)
                embedded = payload.get("embedded") is True if payload else False
                self._write_browser_grant(
                    link_session_id,
                    self._authorize_link(link_session_id),
                    embedded=embedded,
                )
            elif (telegram_session_id := _match(self.path, "/telegram-authorize")) is not None:
                payload = self._read_json(maximum_bytes=16 * 1024)
                init_data = str(payload.get("telegram_init_data") or "") if payload else ""
                if not init_data:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_telegram_auth"})
                    return
                self._write_browser_grant(
                    telegram_session_id,
                    self._authorize_telegram(telegram_session_id, init_data),
                    embedded=payload.get("embedded") is True,
                )
            elif (code_session_id := _match(self.path, "/code-authorize")) is not None:
                payload = self._read_json(maximum_bytes=1024)
                access_code = str(payload.get("access_code") or "") if payload else ""
                if re.fullmatch(r"[0-9]{4}", access_code) is None:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_access_code"})
                    return
                self._write_browser_grant(
                    code_session_id,
                    self._authorize(code_session_id, access_code),
                    embedded=payload.get("embedded") is True,
                )
            elif (handshake_session_id := _match(self.path, "/e2ee-handshake")) is not None:
                self._handshake(handshake_session_id)
            elif (encrypted_session_id := _match(self.path, "/encrypted")) is not None:
                self._encrypted_request(encrypted_session_id)
            else:
                self._write_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed"})

        def do_PUT(self) -> None:
            self._write_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "read_only_share"})

        do_PATCH = do_PUT
        do_DELETE = do_PUT

    return GatewayHandler


def serve(
    *,
    host: str = GATEWAY_HOST,
    port: int = GATEWAY_PORT,
    client_factory: Callable[[], tuple[PlatformClient, str]] = _client,
    key_store: SessionKeyStore | None = None,
) -> None:
    """Run the plugin gateway on loopback; non-loopback binds are refused."""

    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("Tinyhat local app gateway must bind to loopback")
    store = key_store or SessionKeyStore(Path(STATE_DIR) / "sessions")
    server = ThreadingHTTPServer(
        (host, port),
        _handler(client_factory, key_store=store, connections=_ConnectionRegistry()),
    )
    server.serve_forever()


if __name__ == "__main__":
    serve()
