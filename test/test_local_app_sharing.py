"""Tests for the Tinyhat encrypted local application sharing capability."""

from __future__ import annotations

import base64
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))
from package_support import load_local_tinyhat  # noqa: E402

load_local_tinyhat(REPO_ROOT)

from tinyhat import schemas, tools  # noqa: E402
from tinyhat.capabilities.local_app_sharing import connector, crypto, gateway, tool  # noqa: E402
from tinyhat.platform import PlatformError  # noqa: E402

SESSION_ID = "las_AAAAAAAAAAAAAAAAAAAAAAAA"
ACCESS_TOKEN = "B" * 43
ACCESS_CODE = "4821"
COMPUTER_ORIGIN = "https://c-0123456789abcdef01234567.viewd.tinyhat.ai"
CONNECTOR_TOKEN = base64.b64encode(
    json.dumps(
        {
            "a": "35a071f190ad8fd5d612b388d74491ca",
            "t": "123e4567-e89b-42d3-a456-426614174000",
            "s": base64.b64encode(bytes(range(32))).decode("ascii"),
        },
        separators=(",", ":"),
    ).encode("ascii")
).decode("ascii")


def _future_expiry() -> str:
    return datetime.fromtimestamp(time.time() + 3600, tz=UTC).isoformat()


class LocalAppSharingCryptoTests(unittest.TestCase):
    def test_session_private_key_is_mode_0600_and_link_uses_a_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = crypto.SessionKeyStore(Path(directory) / "sessions")
            session_key = store.create(
                session_id=SESSION_ID,
                expires_at_epoch=time.time() + 3600,
            )
            key_path = Path(directory) / "sessions" / f"{SESSION_ID}.json"
            link = crypto.encrypted_link(
                f"{COMPUTER_ORIGIN}/s/{SESSION_ID}", session_key.fingerprint
            )

            self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)
            self.assertIn(f"#{crypto.CONTENT_ENCRYPTION_PROTOCOL}=", link)
            self.assertNotIn("PRIVATE KEY", link)
            self.assertEqual(store.load(SESSION_ID).fingerprint, session_key.fingerprint)

            store.delete(SESSION_ID)
            self.assertFalse(key_path.exists())

    def test_encrypted_envelope_rejects_tampering_and_wrong_context(self) -> None:
        key = bytes(range(32))
        aad = crypto.request_aad(
            session_id=SESSION_ID,
            connection_id="e2e_" + "C" * 24,
            request_id="D" * 24,
        )
        encrypted = crypto.encrypt_json(
            key=key,
            payload={"method": "GET", "target": "/private-marker"},
            aad=aad,
        )
        serialized = json.dumps(encrypted)

        self.assertNotIn("private-marker", serialized)
        self.assertEqual(
            crypto.decrypt_json(key=key, aad=aad, **encrypted)["target"],
            "/private-marker",
        )
        with self.assertRaises(crypto.LocalAppCryptoError):
            crypto.decrypt_json(key=key, aad=aad + b"wrong", **encrypted)


class LocalAppSharingToolTests(unittest.TestCase):
    def test_create_requires_encryption_and_returns_fragment_bound_link(self) -> None:
        requests: list[tuple[str, dict[str, object]]] = []

        class FakeClient:
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                requests.append((path, payload))
                return {
                    "schema_version": "v1",
                    "session_id": SESSION_ID,
                    "link": f"{COMPUTER_ORIGIN}/s/{SESSION_ID}",
                    "access_code": ACCESS_CODE,
                    "label": "Forecast preview",
                    "port": 4310,
                    "status": "active",
                    "created_at": _future_expiry(),
                    "expires_at": _future_expiry(),
                    "content_encryption": crypto.CONTENT_ENCRYPTION_PROTOCOL,
                }

        with tempfile.TemporaryDirectory() as directory:
            key_store = crypto.SessionKeyStore(Path(directory) / "sessions")
            with (
                mock.patch.object(tool, "SESSION_KEY_STORE", key_store),
                mock.patch.object(tool, "_port_is_open", return_value=True),
                mock.patch.object(tool, "ensure_gateway_running"),
                mock.patch.object(
                    tool,
                    "ensure_connector_running",
                    return_value=COMPUTER_ORIGIN,
                ),
                mock.patch.object(tool, "_send_share_button", return_value=True),
                mock.patch.object(
                    tool,
                    "build_platform_client",
                    return_value=(FakeClient(), "gcloud"),
                ),
            ):
                result = json.loads(
                    tool.local_app_sharing(
                        {
                            "action": "create",
                            "port": 4310,
                            "label": "Forecast preview",
                            "ttl_seconds": 900,
                        }
                    )
                )

        self.assertEqual(
            requests,
            [
                (
                    "/hapi/v1/computers/me/local-app-shares/v1",
                    {
                        "port": 4310,
                        "label": "Forecast preview",
                        "ttl_seconds": 900,
                        "content_encryption": crypto.CONTENT_ENCRYPTION_PROTOCOL,
                    },
                )
            ],
        )
        self.assertTrue(result["link"].startswith(f"{COMPUTER_ORIGIN}/s/{SESSION_ID}#"))
        self.assertEqual(result["mini_app_url"], result["link"])
        self.assertEqual(result["access_code"], ACCESS_CODE)
        self.assertEqual(result["content_encryption"], crypto.CONTENT_ENCRYPTION_PROTOCOL)
        self.assertTrue(result["telegram_button_sent"])
        self.assertNotIn("access_token", result)

    def test_list_rebuilds_links_from_local_keys_and_revoke_deletes_them(self) -> None:
        paths: list[tuple[str, str]] = []

        class FakeClient:
            def get_json(self, path: str) -> dict[str, object]:
                paths.append(("GET", path))
                return {
                    "schema_version": "v1",
                    "sessions": [
                        {
                            "session_id": SESSION_ID,
                            "link": f"{COMPUTER_ORIGIN}/s/{SESSION_ID}",
                            "label": "App",
                            "port": 4311,
                            "expires_at": _future_expiry(),
                            "content_encryption": crypto.CONTENT_ENCRYPTION_PROTOCOL,
                        }
                    ],
                }

            def delete_json(self, path: str) -> dict[str, object]:
                paths.append(("DELETE", path))
                return {"session_id": SESSION_ID, "status": "revoked"}

        with tempfile.TemporaryDirectory() as directory:
            key_store = crypto.SessionKeyStore(Path(directory) / "sessions")
            key_store.create(session_id=SESSION_ID, expires_at_epoch=time.time() + 3600)
            with (
                mock.patch.object(tool, "SESSION_KEY_STORE", key_store),
                mock.patch.object(
                    tool,
                    "build_platform_client",
                    return_value=(FakeClient(), "gcloud"),
                ),
            ):
                listed = json.loads(tool.local_app_sharing({"action": "list"}))
                revoked = json.loads(
                    tool.local_app_sharing({"action": "revoke", "session_id": SESSION_ID})
                )

            self.assertFalse((key_store.root / f"{SESSION_ID}.json").exists())

        self.assertIn(f"#{crypto.CONTENT_ENCRYPTION_PROTOCOL}=", listed["sessions"][0]["link"])
        self.assertNotIn("access_code", json.dumps(listed))
        self.assertEqual(revoked["status"], "revoked")
        self.assertEqual(
            paths,
            [
                ("GET", "/hapi/v1/computers/me/local-app-shares/v1"),
                ("DELETE", f"/hapi/v1/computers/me/local-app-shares/v1/{SESSION_ID}"),
            ],
        )

    def test_platform_without_encryption_fails_closed(self) -> None:
        response = {
            "schema_version": "v1",
            "session_id": SESSION_ID,
            "link": f"{COMPUTER_ORIGIN}/s/{SESSION_ID}",
            "access_code": ACCESS_CODE,
            "label": "Preview",
            "port": 4310,
            "status": "active",
            "created_at": _future_expiry(),
            "expires_at": _future_expiry(),
        }
        with self.assertRaisesRegex(ValueError, "end-to-end encrypted"):
            tool._safe_created_payload(response)

    def test_create_rejects_closed_or_gateway_ports_before_platform_call(self) -> None:
        closed = json.loads(
            tool.local_app_sharing({"action": "create", "port": 4312, "label": "Closed app"})
        )
        gateway_port = json.loads(
            tool.local_app_sharing({"action": "create", "port": tool.GATEWAY_PORT, "label": "Bad"})
        )
        self.assertEqual(closed["error"], "invalid_local_app_share_request")
        self.assertIn("no local application", closed["message"])
        self.assertEqual(gateway_port["error"], "invalid_local_app_share_request")

    def test_platform_errors_do_not_echo_sensitive_details(self) -> None:
        with mock.patch.object(
            tool,
            "build_platform_client",
            side_effect=PlatformError("Bearer secret-value was rejected"),
        ):
            result = json.loads(tool.local_app_sharing({"action": "list"}))
        self.assertEqual(result["error"], "local_app_sharing_unavailable")
        self.assertNotIn("secret-value", json.dumps(result))

    def test_share_button_uses_native_mini_app_and_browser_fallback(self) -> None:
        sent: dict[str, object] = {}

        def send_message(**kwargs: object) -> dict[str, bool]:
            sent.update(kwargs)
            return {"ok": True}

        link = f"{COMPUTER_ORIGIN}/s/{SESSION_ID}#{crypto.CONTENT_ENCRYPTION_PROTOCOL}={'F' * 43}"
        created = {
            "label": "Forecast preview",
            "link": link,
            "mini_app_url": link,
            "access_code": ACCESS_CODE,
            "expires_at": _future_expiry(),
        }
        with (
            mock.patch.object(tools, "_telegram_credentials", return_value=("token", "123")),
            mock.patch.object(tools, "_telegram_send_message", side_effect=send_message),
        ):
            self.assertTrue(tool._send_share_button(created))

        self.assertIn(ACCESS_CODE, str(sent["text"]))
        self.assertIn(link, str(sent["text"]))
        self.assertEqual(
            sent["reply_markup"],
            {"inline_keyboard": [[{"text": "View app", "web_app": {"url": link}}]]},
        )

    def test_gateway_health_contract_forces_plaintext_process_replacement(self) -> None:
        self.assertGreaterEqual(tool.GATEWAY_PROTOCOL_VERSION, 8)
        viewer = gateway.VIEWER_PAGE.decode("utf-8")
        self.assertIn("content_encryption", viewer)
        self.assertIn("controllerchange", viewer)
        self.assertIn("service-worker-control-timeout", viewer)
        self.assertNotIn("<iframe", viewer)
        self.assertIn("location.replace", viewer)
        worker = gateway.SERVICE_WORKER.decode("utf-8")
        self.assertIn("app-shell-v3.js", worker)
        self.assertIn("indexedDB.open", worker)
        self.assertIn("persistConfig", worker)
        self.assertIn("loadConfig", worker)
        self.assertIn("worker-src 'none'", worker)
        app_shell = gateway.APP_SHELL.decode("utf-8")
        self.assertIn("history.replaceState", app_shell)
        self.assertIn("sessionStorage.getItem", app_shell)
        self.assertIn(crypto.CONTENT_ENCRYPTION_PROTOCOL, app_shell)
        self.assertNotIn("tgWebAppData", app_shell)

    def test_gateway_launch_does_not_depend_on_checkout_directory_name(self) -> None:
        args = tool._gateway_process_args()
        self.assertEqual(args[0], sys.executable)
        self.assertEqual(args[1], "-c")
        self.assertEqual(Path(args[-1]), REPO_ROOT)
        self.assertIn('spec_from_file_location(\n    "tinyhat"', args[2])
        self.assertNotIn("TINYHAT_LOCAL_DEV_TOKEN", " ".join(args))

    def test_package_exposes_tool_schema_and_encryption_guidance(self) -> None:
        self.assertIn(
            "create", schemas.TINYHAT_LOCAL_APP_SHARING_SCHEMA["properties"]["action"]["enum"]
        )
        self.assertTrue(callable(tools.local_app_sharing))
        skill = (REPO_ROOT / "skills" / "tinyhat-local-app-sharing" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("browser-to-Computer", skill)
        self.assertIn("tinyhat_local_app_sharing", skill)
        self.assertIn("Do not use", skill.split("---", 2)[1])
        self.assertNotIn("tinyhat--runtimes", skill)


class LocalAppSharingConnectorTests(unittest.TestCase):
    def test_connector_uses_computer_endpoint_and_never_returns_token(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        class FakeClient:
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                calls.append((path, payload))
                return {
                    "schema_version": "v1",
                    "hostname": "c-0123456789abcdef01234567.viewd.tinyhat.ai",
                    "public_origin": COMPUTER_ORIGIN,
                    "connector_token": CONNECTOR_TOKEN,
                }

        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            with (
                mock.patch.object(connector, "STATE_DIR", state_dir),
                mock.patch.object(connector, "LOCK_PATH", state_dir / "connector.lock"),
                mock.patch.object(connector, "_write_token", return_value=False),
                mock.patch.object(connector, "_connector_process", return_value=object()),
            ):
                origin = connector.ensure_connector_running(
                    client=FakeClient(),  # type: ignore[arg-type]
                    platform_auth="gcloud",
                )

        self.assertEqual(origin, COMPUTER_ORIGIN)
        self.assertEqual(calls, [("/hapi/v1/computers/me/viewer-tunnel/v1/ensure", {})])
        self.assertNotIn(CONNECTOR_TOKEN, origin)

    def test_connector_process_uses_private_token_file_not_token_argument(self) -> None:
        process = mock.Mock()
        process.pid = 4321
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            token_path = state_dir / "cloudflared.token"
            with (
                mock.patch.object(connector, "TOKEN_PATH", token_path),
                mock.patch.object(connector, "PID_PATH", state_dir / "cloudflared.pid"),
                mock.patch.object(connector, "LOG_PATH", state_dir / "cloudflared.log"),
                mock.patch.object(connector.subprocess, "Popen", return_value=process) as popen,
                mock.patch.object(connector, "_connector_ready", return_value=True),
                mock.patch.object(connector.time, "sleep"),
            ):
                connector._start_connector(Path("/private/cloudflared"))

        args = popen.call_args.args[0]
        self.assertEqual(
            args,
            [
                "/private/cloudflared",
                "tunnel",
                "--no-autoupdate",
                "--metrics",
                "127.0.0.1:9322",
                "--grace-period",
                "5s",
                "run",
                "--token-file",
                str(token_path),
            ],
        )
        self.assertNotIn(CONNECTOR_TOKEN, " ".join(args))

    def test_connector_rejects_shared_or_unscoped_hostnames(self) -> None:
        for hostname in (
            "viewd.tinyhat.ai",
            "c-not-opaque.viewd.tinyhat.ai",
            "c-0123456789abcdef01234567.example.com",
        ):
            with (
                self.subTest(hostname=hostname),
                self.assertRaisesRegex(ValueError, "invalid Computer viewer"),
            ):
                connector._validated_connector_payload(
                    {
                        "schema_version": "v1",
                        "hostname": hostname,
                        "public_origin": f"https://{hostname}",
                        "connector_token": CONNECTOR_TOKEN,
                    }
                )


class _UpstreamHandler(BaseHTTPRequestHandler):
    seen_cookie: str | None = None

    def log_message(self, format_string: str, *args: object) -> None:
        _ = (format_string, args)

    def do_GET(self) -> None:
        type(self).seen_cookie = self.headers.get("cookie")
        body = b"<h1>Shared local app reached: private-marker</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Set-Cookie", "app_session=allowed; Path=/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class LocalAppSharingGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        _UpstreamHandler.seen_cookie = None
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
        self.upstream_thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.upstream_thread.start()
        self.upstream_port = int(self.upstream.server_address[1])
        self.platform_paths: list[str] = []
        self.expiry = _future_expiry()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.key_store = crypto.SessionKeyStore(Path(self.temp_dir.name) / "sessions")
        self.session_key = self.key_store.create(
            session_id=SESSION_ID,
            expires_at_epoch=time.time() + 3600,
        )
        test_case = self

        class FakePlatformClient:
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                test_case.platform_paths.append(path)
                common = {
                    "schema_version": "v1",
                    "session_id": SESSION_ID,
                    "expires_at": test_case.expiry,
                    "content_encryption": crypto.CONTENT_ENCRYPTION_PROTOCOL,
                }
                if path.endswith("/authorize") and payload == {"access_code": ACCESS_CODE}:
                    return {**common, "access_token": ACCESS_TOKEN}
                if path.endswith("/authorize-telegram") and payload == {
                    "telegram_init_data": "signed-owner-init-data"
                }:
                    return {**common, "access_token": ACCESS_TOKEN}
                if path.endswith("/resolve") and payload == {"access_token": ACCESS_TOKEN}:
                    return {**common, "port": test_case.upstream_port, "label": "Preview"}
                raise PlatformError("unauthorized", status_code=401)

        handler = gateway._handler(
            lambda: (FakePlatformClient(), "gcloud"),
            key_store=self.key_store,
            connections=gateway._ConnectionRegistry(),
        )
        self.gateway = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.gateway_thread = threading.Thread(target=self.gateway.serve_forever, daemon=True)
        self.gateway_thread.start()
        self.gateway_port = int(self.gateway.server_address[1])

    def tearDown(self) -> None:
        self.gateway.shutdown()
        self.gateway.server_close()
        self.gateway_thread.join(timeout=2)
        self.upstream.shutdown()
        self.upstream.server_close()
        self.upstream_thread.join(timeout=2)
        self.temp_dir.cleanup()

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        cookie: str | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.gateway_port)
        body = json.dumps(payload).encode() if payload is not None else None
        headers: dict[str, str] = {}
        if body is not None:
            headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        if cookie:
            headers["Cookie"] = cookie
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
        response_headers = {name.lower(): value for name, value in response.getheaders()}
        status = response.status
        connection.close()
        return status, response_headers, response_body

    def _authorize(self) -> str:
        status, headers, _ = self._request(
            "POST",
            f"/s/{SESSION_ID}/code-authorize",
            payload={"access_code": ACCESS_CODE},
        )
        self.assertEqual(status, 200)
        return headers["set-cookie"].split(";", 1)[0]

    def _handshake(self, cookie: str) -> tuple[str, bytes]:
        status, _, key_body = self._request("GET", f"/s/{SESSION_ID}/e2ee-key", cookie=cookie)
        self.assertEqual(status, 200)
        key_payload = json.loads(key_body)
        self.assertEqual(key_payload["fingerprint"], self.session_key.fingerprint)

        browser_private = ec.generate_private_key(ec.SECP256R1())
        status, _, handshake_body = self._request(
            "POST",
            f"/s/{SESSION_ID}/e2ee-handshake",
            cookie=cookie,
            payload={"browser_public_jwk": crypto._public_jwk(browser_private.public_key())},
        )
        self.assertEqual(status, 200)
        handshake = json.loads(handshake_body)
        server_public = crypto._public_key_from_jwk(key_payload["public_key_jwk"])
        shared = browser_private.exchange(ec.ECDH(), server_public)
        salt = base64.urlsafe_b64decode(handshake["salt"] + "==")
        info = (
            f"{crypto.CONTENT_ENCRYPTION_PROTOCOL}\0{SESSION_ID}\0{self.session_key.fingerprint}"
        ).encode("ascii")
        content_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(
            shared
        )
        return handshake["connection_id"], content_key

    def _encrypted_get(
        self,
        *,
        cookie: str,
        connection_id: str,
        content_key: bytes,
        request_id: str,
    ) -> tuple[int, bytes, dict[str, object]]:
        encrypted = crypto.encrypt_json(
            key=content_key,
            payload={"method": "GET", "target": "/", "headers": {}},
            aad=crypto.request_aad(
                session_id=SESSION_ID,
                connection_id=connection_id,
                request_id=request_id,
            ),
        )
        outer = {
            "content_encryption": crypto.CONTENT_ENCRYPTION_PROTOCOL,
            "connection_id": connection_id,
            "request_id": request_id,
            **encrypted,
        }
        status, _, raw = self._request(
            "POST", f"/s/{SESSION_ID}/encrypted", cookie=cookie, payload=outer
        )
        return status, raw, json.loads(raw)

    def test_shell_starts_as_spinner_only_and_plaintext_proxy_is_gone(self) -> None:
        status, _, body = self._request("GET", f"/s/{SESSION_ID}")
        html = body.decode()
        self.assertEqual(status, 200)
        self.assertIn('id="loading"', html)
        self.assertIn('id="code-page" hidden', html)
        self.assertNotIn("Verifying your Telegram account", html)
        direct_status, _, direct = self._request("GET", f"/s/{SESSION_ID}/app/")
        self.assertEqual(direct_status, 426)
        self.assertEqual(json.loads(direct)["error"], "encrypted_transport_required")

        shell_status, _, shell = self._request("GET", "/__tinyhat_share/app-shell-v3.js")
        self.assertEqual(shell_status, 200)
        self.assertIn(b"history.replaceState", shell)

    def test_code_auth_round_trips_only_ciphertext_and_rejects_replay(self) -> None:
        cookie = self._authorize()
        connection_id, content_key = self._handshake(cookie)
        request_id = "request_" + "D" * 24
        status, encrypted_wire_body, encrypted_payload = self._encrypted_get(
            cookie=cookie,
            connection_id=connection_id,
            content_key=content_key,
            request_id=request_id,
        )

        self.assertEqual(status, 200)
        self.assertNotIn(b"private-marker", encrypted_wire_body)
        decrypted = crypto.decrypt_json(
            key=content_key,
            nonce=str(encrypted_payload["nonce"]),
            ciphertext=str(encrypted_payload["ciphertext"]),
            aad=crypto.response_aad(
                session_id=SESSION_ID,
                connection_id=connection_id,
                request_id=request_id,
            ),
        )
        decoded_body = base64.urlsafe_b64decode(str(decrypted["body"]) + "==")
        self.assertIn(b"private-marker", decoded_body)
        self.assertNotIn("set-cookie", json.dumps(decrypted).lower())

        replay_status, _, _ = self._encrypted_get(
            cookie=cookie,
            connection_id=connection_id,
            content_key=content_key,
            request_id=request_id,
        )
        self.assertEqual(replay_status, 400)

    def test_telegram_owner_auth_sets_session_scoped_grant_without_code(self) -> None:
        status, headers, body = self._request(
            "POST",
            f"/s/{SESSION_ID}/telegram-authorize",
            payload={"telegram_init_data": "signed-owner-init-data"},
        )
        self.assertEqual(status, 200, body)
        cookie = headers["set-cookie"]
        self.assertIn(gateway._cookie_name(SESSION_ID), cookie)
        self.assertIn("SameSite=None", cookie)
        self.assertIn("Partitioned", cookie)

    def test_health_declares_encryption_and_all_writes_are_blocked(self) -> None:
        status, _, body = self._request("GET", "/__tinyhat_share/health")
        self.assertEqual(status, 200)
        self.assertEqual(
            json.loads(body),
            {
                "ok": True,
                "protocol_version": tool.GATEWAY_PROTOCOL_VERSION,
                "content_encryption": crypto.CONTENT_ENCRYPTION_PROTOCOL,
            },
        )
        for method in ("PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                blocked_status, _, blocked_body = self._request(method, "/anything")
                self.assertEqual(blocked_status, 405)
                self.assertEqual(json.loads(blocked_body)["error"], "read_only_share")


if __name__ == "__main__":
    unittest.main()
