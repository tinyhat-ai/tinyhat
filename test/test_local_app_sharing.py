"""Tests for the Tinyhat local application sharing capability."""

from __future__ import annotations

import http.client
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))
from package_support import load_local_tinyhat  # noqa: E402

load_local_tinyhat(REPO_ROOT)

from tinyhat import schemas, tools  # noqa: E402
from tinyhat.capabilities.local_app_sharing import gateway, tool  # noqa: E402
from tinyhat.platform import PlatformError  # noqa: E402

SESSION_ID = "las_AAAAAAAAAAAAAAAAAAAAAAAA"
ACCESS_TOKEN = "B" * 43
ACCESS_CODE = "4821"


class LocalAppSharingToolTests(unittest.TestCase):
    def test_create_uses_fixed_computer_api_and_returns_link_and_code(self) -> None:
        requests: list[tuple[str, dict[str, object]]] = []

        class FakeClient:
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                requests.append((path, payload))
                return {
                    "schema_version": "v1",
                    "session_id": SESSION_ID,
                    "link": f"https://viewd.tinyhat.ai/s/{SESSION_ID}",
                    "access_code": ACCESS_CODE,
                    "label": "Forecast preview",
                    "port": 4310,
                    "status": "active",
                    "created_at": "2026-08-21T15:00:00Z",
                    "expires_at": "2026-08-21T15:15:00Z",
                }

        with (
            mock.patch.object(tool, "_port_is_open", return_value=True),
            mock.patch.object(tool, "ensure_gateway_running"),
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
                    },
                )
            ],
        )
        self.assertEqual(result["link"], f"https://viewd.tinyhat.ai/s/{SESSION_ID}")
        self.assertEqual(result["mini_app_url"], result["link"])
        self.assertEqual(result["access_code"], ACCESS_CODE)
        self.assertTrue(result["telegram_button_sent"])
        self.assertNotIn("access_token", result)

    def test_list_and_revoke_never_invent_identity_or_codes(self) -> None:
        paths: list[tuple[str, str]] = []

        class FakeClient:
            def get_json(self, path: str) -> dict[str, object]:
                paths.append(("GET", path))
                return {
                    "schema_version": "v1",
                    "sessions": [
                        {
                            "session_id": SESSION_ID,
                            "link": f"https://view.tinyhat.ai/s/{SESSION_ID}",
                            "label": "App",
                            "port": 4311,
                            "expires_at": "2026-08-21T15:15:00Z",
                        }
                    ],
                }

            def delete_json(self, path: str) -> dict[str, object]:
                paths.append(("DELETE", path))
                return {"session_id": SESSION_ID, "status": "revoked"}

        with mock.patch.object(
            tool,
            "build_platform_client",
            return_value=(FakeClient(), "gcloud"),
        ):
            listed = json.loads(tool.local_app_sharing({"action": "list"}))
            revoked = json.loads(
                tool.local_app_sharing({"action": "revoke", "session_id": SESSION_ID})
            )

        self.assertEqual(
            paths,
            [
                ("GET", "/hapi/v1/computers/me/local-app-shares/v1"),
                (
                    "DELETE",
                    f"/hapi/v1/computers/me/local-app-shares/v1/{SESSION_ID}",
                ),
            ],
        )
        self.assertNotIn("access_code", json.dumps(listed))
        self.assertEqual(revoked["status"], "revoked")

    def test_create_rejects_closed_or_gateway_ports_before_platform_call(self) -> None:
        closed = json.loads(
            tool.local_app_sharing({"action": "create", "port": 4312, "label": "Closed app"})
        )
        gateway_port = json.loads(
            tool.local_app_sharing({"action": "create", "port": tool.GATEWAY_PORT, "label": "Bad"})
        )
        self.assertEqual(closed["error"], "invalid_local_app_share_request")
        self.assertIn("no local application", closed["message"])
        self.assertEqual(
            gateway_port["error"],
            "invalid_local_app_share_request",
        )

    def test_platform_errors_do_not_echo_sensitive_details(self) -> None:
        with mock.patch.object(
            tool,
            "build_platform_client",
            side_effect=PlatformError("Bearer secret-value was rejected"),
        ):
            result = json.loads(tool.local_app_sharing({"action": "list"}))
        self.assertEqual(result["error"], "local_app_sharing_unavailable")
        self.assertNotIn("secret-value", json.dumps(result))

    def test_share_button_uses_native_mini_app_and_includes_browser_fallback(self) -> None:
        sent: dict[str, object] = {}

        def send_message(**kwargs: object) -> dict[str, bool]:
            sent.update(kwargs)
            return {"ok": True}

        created = {
            "label": "Forecast preview",
            "link": f"https://viewd.tinyhat.ai/s/{SESSION_ID}",
            "mini_app_url": f"https://viewd.tinyhat.ai/s/{SESSION_ID}",
            "access_code": ACCESS_CODE,
            "expires_at": "2026-08-21T15:15:00Z",
        }
        with (
            mock.patch.object(tools, "_telegram_credentials", return_value=("token", "123")),
            mock.patch.object(tools, "_telegram_send_message", side_effect=send_message),
        ):
            self.assertTrue(tool._send_share_button(created))

        self.assertIn(ACCESS_CODE, str(sent["text"]))
        self.assertIn(created["link"], str(sent["text"]))
        self.assertEqual(
            sent["reply_markup"],
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "View app",
                            "web_app": {"url": created["mini_app_url"]},
                        }
                    ]
                ]
            },
        )

    def test_gateway_launch_does_not_depend_on_checkout_directory_name(self) -> None:
        args = tool._gateway_process_args()
        self.assertEqual(args[0], sys.executable)
        self.assertEqual(args[1], "-c")
        self.assertEqual(Path(args[-1]), REPO_ROOT)
        self.assertIn('spec_from_file_location(\n    "tinyhat"', args[2])
        self.assertNotIn("TINYHAT_LOCAL_DEV_TOKEN", " ".join(args))

    def test_package_exposes_tool_schema_and_skill(self) -> None:
        self.assertIn(
            "create", schemas.TINYHAT_LOCAL_APP_SHARING_SCHEMA["properties"]["action"]["enum"]
        )
        self.assertTrue(callable(tools.local_app_sharing))
        skill = (REPO_ROOT / "skills" / "tinyhat-local-app-sharing" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("tinyhat_local_app_sharing", skill)
        self.assertIn("Do not use", skill.split("---", 2)[1])
        self.assertNotIn("tinyhat--runtimes", skill)


class _UpstreamHandler(BaseHTTPRequestHandler):
    seen_cookie: str | None = None
    seen_connection: str | None = None
    seen_upgrade: str | None = None

    def log_message(self, format_string: str, *args: object) -> None:
        _ = (format_string, args)

    def do_GET(self) -> None:
        type(self).seen_cookie = self.headers.get("cookie")
        type(self).seen_connection = self.headers.get("connection")
        type(self).seen_upgrade = self.headers.get("upgrade")
        body = b"<h1>Shared local app reached</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Set-Cookie", "app_session=allowed; Path=/")
        self.send_header(
            "Set-Cookie",
            f"{gateway.COOKIE_NAME}=must-not-overwrite; Path=/",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class LocalAppSharingGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        _UpstreamHandler.seen_cookie = None
        _UpstreamHandler.seen_connection = None
        _UpstreamHandler.seen_upgrade = None
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
        self.upstream_thread = threading.Thread(
            target=self.upstream.serve_forever,
            daemon=True,
        )
        self.upstream_thread.start()
        upstream_port = int(self.upstream.server_address[1])
        self.platform_paths: list[str] = []

        test_case = self

        class FakePlatformClient:
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                test_case.platform_paths.append(path)
                if path.endswith("/authorize") and payload == {"access_code": ACCESS_CODE}:
                    return {"access_token": ACCESS_TOKEN}
                if path.endswith("/authorize-telegram") and payload == {
                    "telegram_init_data": "signed-owner-init-data"
                }:
                    return {"access_token": ACCESS_TOKEN}
                if path.endswith("/resolve") and payload == {"access_token": ACCESS_TOKEN}:
                    return {"port": upstream_port, "label": "Preview"}
                raise PlatformError("unauthorized", status_code=401)

        handler = gateway._handler(lambda: (FakePlatformClient(), "gcloud"))
        self.gateway = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.gateway_thread = threading.Thread(
            target=self.gateway.serve_forever,
            daemon=True,
        )
        self.gateway_thread.start()
        self.gateway_port = int(self.gateway.server_address[1])

    def tearDown(self) -> None:
        self.gateway.shutdown()
        self.gateway.server_close()
        self.gateway_thread.join(timeout=2)
        self.upstream.shutdown()
        self.upstream.server_close()
        self.upstream_thread.join(timeout=2)

    def test_code_gate_resolves_through_platform_and_proxies_read_only(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.gateway_port)
        connection.request("GET", f"/s/{SESSION_ID}")
        locked = connection.getresponse()
        locked_body = locked.read().decode()
        self.assertEqual(locked.status, 401)
        self.assertIn("Access code", locked_body)
        self.assertIn('inputmode="numeric"', locked_body)
        self.assertIn('pattern="[0-9]{4}"', locked_body)
        self.assertIn("telegram-web-app.js", locked_body)
        self.assertIn('id="loading"', locked_body)
        self.assertIn('id="code-page" hidden', locked_body)
        self.assertNotIn("Verifying your Telegram account", locked_body)

        form = urlencode({"code": ACCESS_CODE})
        connection.request(
            "POST",
            f"/s/{SESSION_ID}",
            body=form,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(form)),
            },
        )
        unlocked = connection.getresponse()
        unlocked.read()
        self.assertEqual(unlocked.status, 303)
        self.assertEqual(unlocked.getheader("Location"), f"/s/{SESSION_ID}")
        cookie = unlocked.getheader("Set-Cookie")
        self.assertIsNotNone(cookie)
        self.assertIn("SameSite=None", str(cookie))
        self.assertIn("Partitioned", str(cookie))
        cookie_value = str(cookie).split(";", 1)[0]

        connection.request(
            "GET",
            f"/s/{SESSION_ID}",
            headers={"Cookie": f"{cookie_value}; app_request=visible"},
        )
        proxied = connection.getresponse()
        body = proxied.read().decode()
        response_cookies = proxied.getheaders()
        connection.close()

        self.assertEqual(proxied.status, 200)
        self.assertIn("Shared local app reached", body)
        self.assertEqual(_UpstreamHandler.seen_cookie, "app_request=visible")
        self.assertIn(
            ("Set-Cookie", "app_session=allowed; Path=/"),
            response_cookies,
        )
        self.assertNotIn("must-not-overwrite", str(response_cookies))
        self.assertTrue(any(path.endswith("/authorize") for path in self.platform_paths))
        self.assertTrue(any(path.endswith("/resolve") for path in self.platform_paths))

    def test_websocket_upgrade_headers_are_rejected(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.gateway_port)
        connection.request(
            "GET",
            f"/s/{SESSION_ID}",
            headers={
                "Connection": "Upgrade",
                "Cookie": f"{gateway.COOKIE_NAME}={SESSION_ID}.{ACCESS_TOKEN}",
                "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                "Sec-WebSocket-Version": "13",
                "Upgrade": "websocket",
            },
        )
        response = connection.getresponse()
        response.read()
        connection.close()

        self.assertEqual(response.status, 200)
        self.assertNotEqual(response.status, 101)
        self.assertIsNone(response.getheader("Upgrade"))
        self.assertIsNone(_UpstreamHandler.seen_connection)
        self.assertIsNone(_UpstreamHandler.seen_upgrade)

    def test_telegram_owner_init_data_sets_the_browser_grant_without_code(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.gateway_port)
        body = json.dumps({"telegram_init_data": "signed-owner-init-data"})
        connection.request(
            "POST",
            f"/s/{SESSION_ID}/telegram-authorize",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body.encode())),
            },
        )
        authorized = connection.getresponse()
        authorized.read()
        self.assertEqual(authorized.status, 200)
        cookie = authorized.getheader("Set-Cookie")
        self.assertIsNotNone(cookie)
        self.assertIn("SameSite=None", str(cookie))
        self.assertIn("Partitioned", str(cookie))
        self.assertTrue(
            any(
                path.endswith(f"local-app-shares/v1/{SESSION_ID}/authorize-telegram")
                for path in self.platform_paths
            )
        )
        connection.close()

    def test_health_is_public_but_writes_are_blocked(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.gateway_port)
        connection.request("GET", "/__tinyhat_share/health")
        health = connection.getresponse()
        self.assertEqual(
            json.loads(health.read()),
            {"ok": True, "protocol_version": tool.GATEWAY_PROTOCOL_VERSION},
        )
        self.assertEqual(health.status, 200)

        connection.request("PUT", "/anything", body=b"write")
        blocked = connection.getresponse()
        payload = json.loads(blocked.read())
        connection.close()
        self.assertEqual(blocked.status, 405)
        self.assertEqual(payload["error"], "read_only_pilot")


if __name__ == "__main__":
    unittest.main()
