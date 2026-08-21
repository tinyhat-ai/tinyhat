"""Loopback-only HTTP gateway for Tinyhat local application shares."""

from __future__ import annotations

import html
import http.client
import json
import re
from collections.abc import Callable
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from ...platform import PlatformClient, PlatformError, build_platform_client, computer_api_path
from .tool import (
    GATEWAY_HOST,
    GATEWAY_PORT,
    GATEWAY_PROTOCOL_VERSION,
    SESSION_ID_RE,
)

COOKIE_NAME = "__Host-tinyhat_local_app_share"
MAX_FORM_BYTES = 1024
MAX_TELEGRAM_INIT_DATA_BYTES = 16 * 1024
MAX_PORT = 65535
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


def _cookie_value(session_id: str, access_token: str) -> str:
    return f"{session_id}.{access_token}"


def _browser_grant_cookie(session_id: str, access_token: str) -> str:
    return (
        f"{COOKIE_NAME}={_cookie_value(session_id, access_token)}; "
        "Path=/; Secure; HttpOnly; SameSite=None; Partitioned"
    )


def _parse_cookie(header: str | None) -> tuple[str, str] | None:
    if not header:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(header)
    except Exception:
        return None
    morsel = cookie.get(COOKIE_NAME)
    if morsel is None:
        return None
    session_id, separator, access_token = morsel.value.partition(".")
    if (
        not separator
        or SESSION_ID_RE.fullmatch(session_id) is None
        or re.fullmatch(r"[A-Za-z0-9_-]{32,256}", access_token) is None
    ):
        return None
    return session_id, access_token


def _without_gateway_cookie(header: str | None) -> str | None:
    if not header:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(header)
    except Exception:
        return None
    cookie.pop(COOKIE_NAME, None)
    values = [f"{name}={morsel.value}" for name, morsel in cookie.items()]
    return "; ".join(values) or None


def _session_from_path(path: str) -> str | None:
    clean_path = urlsplit(path).path
    match = re.fullmatch(r"/s/(las_[A-Za-z0-9_-]{20,80})/?", clean_path)
    return match.group(1) if match else None


def _telegram_authorize_session_from_path(path: str) -> str | None:
    clean_path = urlsplit(path).path
    match = re.fullmatch(
        r"/s/(las_[A-Za-z0-9_-]{20,80})/telegram-authorize/?",
        clean_path,
    )
    return match.group(1) if match else None


def _code_page(*, error_message: str | None = None) -> bytes:
    error_html = (
        f'<p class="error" role="alert">{html.escape(error_message)}</p>' if error_message else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Open shared Tinyhat app</title>
<style>[hidden]{{display:none!important}}
body{{font:16px system-ui;margin:0;background:#f5f5f0;color:#171717}}
main{{max-width:28rem;margin:12vh auto;padding:2rem;background:white;border:1px solid #bbb}}
input,button{{box-sizing:border-box;width:100%;padding:.8rem;margin-top:.75rem;font:inherit}}
button{{background:#171717;color:white;border:0}}.error{{color:#a00}}
#loading{{display:grid;place-items:center;min-height:14rem;background:transparent;border:0}}
.spinner{{width:2rem;height:2rem;border:.2rem solid #d7d7d2;border-top-color:#171717;
border-radius:50%;animation:spin .8s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}</style></head>
<body><main id="loading"><span class="spinner" role="status" aria-label="Loading"></span></main>
<main id="code-page" hidden><h1>Open shared app</h1><p>Enter the code your agent sent you.</p>
{error_html}
<form id="code-form" method="post"><label for="code">Access code</label>
<input id="code" name="code" autocomplete="one-time-code" inputmode="numeric"
pattern="[0-9]{{4}}" minlength="4" maxlength="4" required>
<button type="submit">View app</button></form></main>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script>(() => {{
  const app = window.Telegram && window.Telegram.WebApp;
  const loading = document.getElementById('loading');
  const codePage = document.getElementById('code-page');
  if (!app || !app.initData) {{
    loading.hidden = true;
    codePage.hidden = false;
    return;
  }}
  app.ready();
  app.expand();
  const path = window.location.pathname.replace(/\\/$/, '');
  fetch(`${{path}}/telegram-authorize`, {{
    method: 'POST',
    credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{telegram_init_data: app.initData}}),
  }}).then(async response => {{
    if (!response.ok) throw new Error('not authorized');
    window.location.replace(path);
  }}).catch(() => {{
    loading.hidden = true;
    codePage.hidden = false;
  }});
}})();</script></body></html>""".encode()


def _handler(
    client_factory: Callable[[], tuple[PlatformClient, str]],
) -> type[BaseHTTPRequestHandler]:
    class GatewayHandler(BaseHTTPRequestHandler):
        server_version = "TinyhatLocalAppGateway/1"

        def log_message(self, format_string: str, *args: Any) -> None:
            _ = (format_string, args)

        def _security_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")

        def _write_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self._security_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _write_code_page(self, status: int, message: str | None = None) -> None:
            body = _code_page(error_message=message)
            self.send_response(status)
            self._security_headers()
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline' https://telegram.org; connect-src 'self'; "
                "form-action 'self'; frame-ancestors https://web.telegram.org "
                "https://*.telegram.org; base-uri 'none'",
            )
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _resolve(self, session_id: str, access_token: str) -> dict[str, Any] | None:
            try:
                client, platform_auth = client_factory()
                return client.post_json(
                    computer_api_path(
                        platform_auth,
                        f"local-app-shares/v1/{quote(session_id, safe='')}/resolve",
                    ),
                    {"access_token": access_token},
                )
            except PlatformError:
                return None

        def _authorize(self, session_id: str, access_code: str) -> dict[str, Any] | None:
            try:
                client, platform_auth = client_factory()
                return client.post_json(
                    computer_api_path(
                        platform_auth,
                        f"local-app-shares/v1/{quote(session_id, safe='')}/authorize",
                    ),
                    {"access_code": access_code},
                )
            except PlatformError:
                return None

        def _authorize_telegram(
            self, session_id: str, telegram_init_data: str
        ) -> dict[str, Any] | None:
            try:
                client, platform_auth = client_factory()
                return client.post_json(
                    computer_api_path(
                        platform_auth,
                        f"local-app-shares/v1/{quote(session_id, safe='')}/authorize-telegram",
                    ),
                    {"telegram_init_data": telegram_init_data},
                )
            except PlatformError:
                return None

        def _write_browser_grant(self, session_id: str, token: str) -> None:
            self.send_response(HTTPStatus.OK)
            self._security_headers()
            self.send_header(
                "Set-Cookie",
                _browser_grant_cookie(session_id, token),
            )
            self.send_header("Content-Type", "application/json")
            body = b'{"ok":true}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized_target(self) -> tuple[str, int] | None:
            grant = _parse_cookie(self.headers.get("cookie"))
            if grant is None:
                return None
            session_id, access_token = grant
            resolved = self._resolve(session_id, access_token)
            if not isinstance(resolved, dict):
                return None
            port = resolved.get("port")
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= MAX_PORT:
                return None
            return session_id, port

        def _write_upstream_response(
            self,
            *,
            status: int,
            reason: str | None,
            response_headers: list[tuple[str, str]],
            body: bytes,
        ) -> None:
            self.send_response(status, reason)
            self._security_headers()
            for key, original_value in response_headers:
                lower = key.lower()
                if lower in HOP_BY_HOP_HEADERS or lower in {
                    "content-length",
                    "cache-control",
                    "pragma",
                }:
                    continue
                if lower == "set-cookie" and original_value.lstrip().startswith(f"{COOKIE_NAME}="):
                    continue
                value = original_value
                if lower == "location":
                    location = urlsplit(value)
                    if location.hostname in {"localhost", "127.0.0.1"}:
                        value = location.path or "/"
                        if location.query:
                            value = f"{value}?{location.query}"
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _proxy(self, *, session_id: str, port: int) -> None:
            parsed = urlsplit(self.path)
            upstream_path = parsed.path
            if _session_from_path(self.path) == session_id:
                upstream_path = "/"
            if parsed.query:
                upstream_path = f"{upstream_path}?{parsed.query}"
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in HOP_BY_HOP_HEADERS
                and key.lower() not in {"host", "content-length"}
            }
            upstream_cookie = _without_gateway_cookie(self.headers.get("cookie"))
            if upstream_cookie:
                headers["Cookie"] = upstream_cookie
            else:
                headers.pop("Cookie", None)
            headers["Host"] = f"127.0.0.1:{port}"
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
            try:
                connection.request(self.command, upstream_path, headers=headers)
                response = connection.getresponse()
                body = response.read()
                status = response.status
                reason = response.reason
                response_headers = response.getheaders()
            except OSError:
                self._write_json(HTTPStatus.BAD_GATEWAY, {"error": "local_app_unavailable"})
                return
            finally:
                connection.close()

            self._write_upstream_response(
                status=status,
                reason=reason,
                response_headers=response_headers,
                body=body,
            )

        def do_GET(self) -> None:
            if urlsplit(self.path).path == "/__tinyhat_share/health":
                self._write_json(
                    HTTPStatus.OK,
                    {"ok": True, "protocol_version": GATEWAY_PROTOCOL_VERSION},
                )
                return
            requested_session = _session_from_path(self.path)
            target = self._authorized_target()
            if target is None:
                if requested_session is not None:
                    self._write_code_page(HTTPStatus.UNAUTHORIZED)
                else:
                    self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "share_access_required"})
                return
            session_id, port = target
            if requested_session is not None and requested_session != session_id:
                self._write_code_page(HTTPStatus.UNAUTHORIZED)
                return
            self._proxy(session_id=session_id, port=port)

        def do_HEAD(self) -> None:
            self.do_GET()

        def do_POST(self) -> None:
            telegram_session_id = _telegram_authorize_session_from_path(self.path)
            if telegram_session_id is not None:
                try:
                    length = int(self.headers.get("content-length") or "0")
                except ValueError:
                    length = 0
                if not 1 <= length <= MAX_TELEGRAM_INIT_DATA_BYTES:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_telegram_auth"})
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8", errors="strict"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_telegram_auth"})
                    return
                telegram_init_data = (
                    str(payload.get("telegram_init_data") or "").strip()
                    if isinstance(payload, dict)
                    else ""
                )
                if not telegram_init_data:
                    self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_telegram_auth"})
                    return
                authorized = self._authorize_telegram(
                    telegram_session_id,
                    telegram_init_data,
                )
                token = authorized.get("access_token") if isinstance(authorized, dict) else None
                if (
                    not isinstance(token, str)
                    or re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token) is None
                ):
                    self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_telegram_auth"})
                    return
                self._write_browser_grant(telegram_session_id, token)
                return

            session_id = _session_from_path(self.path)
            if session_id is None:
                self._write_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed"})
                return
            try:
                length = int(self.headers.get("content-length") or "0")
            except ValueError:
                length = 0
            if not 1 <= length <= MAX_FORM_BYTES:
                self._write_code_page(HTTPStatus.BAD_REQUEST, "Enter the four-digit code.")
                return
            form = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
            access_code = str((form.get("code") or [""])[0]).strip()
            if re.fullmatch(r"[0-9]{4}", access_code) is None:
                self._write_code_page(HTTPStatus.UNAUTHORIZED, "That code is not valid.")
                return
            authorized = self._authorize(session_id, access_code)
            token = authorized.get("access_token") if isinstance(authorized, dict) else None
            if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token) is None:
                self._write_code_page(
                    HTTPStatus.UNAUTHORIZED, "That code is not valid or has expired."
                )
                return
            self.send_response(HTTPStatus.SEE_OTHER)
            self._security_headers()
            self.send_header(
                "Set-Cookie",
                f"{COOKIE_NAME}={_cookie_value(session_id, token)}; Path=/; Secure; HttpOnly; SameSite=Lax",
            )
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_PUT(self) -> None:
            self._write_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "read_only_pilot"})

        do_PATCH = do_PUT
        do_DELETE = do_PUT

    return GatewayHandler


def serve(
    *,
    host: str = GATEWAY_HOST,
    port: int = GATEWAY_PORT,
    client_factory: Callable[[], tuple[PlatformClient, str]] = _client,
) -> None:
    """Run the plugin gateway on loopback; non-loopback binds are refused."""

    if host not in {"127.0.0.1", "::1"}:
        raise ValueError("Tinyhat local app gateway must bind to loopback")
    server = ThreadingHTTPServer((host, port), _handler(client_factory))
    server.serve_forever()


if __name__ == "__main__":
    serve()
