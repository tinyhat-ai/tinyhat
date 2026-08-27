"""Tests for the interactive Computer desktop capability."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))
from package_support import load_local_tinyhat  # noqa: E402

load_local_tinyhat(REPO_ROOT)

from tinyhat import tools as root_tools  # noqa: E402
from tinyhat.capabilities.computer_desktop import tool  # noqa: E402
from tinyhat.platform import PlatformError  # noqa: E402

SESSION_ID = "dsk_012345678901234567890123"
LINK = f"https://tinyhat.test/tinyhat/desktop/{SESSION_ID}"


def _platform_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "v1",
        "session_id": SESSION_ID,
        "link": LINK,
        "access_code": "123456",
        "expires_at": "2026-08-25T12:00:00Z",
        "view_only": False,
    }
    payload.update(overrides)
    return payload


class ComputerDesktopToolTests(unittest.TestCase):
    def test_creates_owner_connection_without_transport_details(self) -> None:
        original = tool.build_platform_client
        original_send = tool._send_desktop_button
        calls: list[tuple[str, dict[str, object]]] = []
        sent: list[dict[str, object]] = []

        class FakeClient:
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                calls.append((path, payload))
                return _platform_payload(
                    tailnet_ip="100.64.0.1",
                    vnc_password="must-not-leak",
                )

        try:
            tool.build_platform_client = lambda: (FakeClient(), "gcloud")
            tool._send_desktop_button = lambda created: bool(
                sent.append(created) or True
            )
            result = json.loads(tool.computer_desktop())
        finally:
            tool.build_platform_client = original
            tool._send_desktop_button = original_send

        self.assertEqual(
            calls,
            [("/hapi/v1/computers/me/desktop-sessions/v1", {})],
        )
        self.assertEqual(result["access_code"], "123456")
        self.assertEqual(result["button_label"], "Open desktop")
        self.assertTrue(result["interactive"])
        self.assertTrue(result["telegram_button_sent"])
        self.assertEqual(sent[0]["link"], result["link"])
        serialized = json.dumps(result)
        self.assertNotIn("session_id", result)
        self.assertNotIn("tailnet", serialized)
        self.assertNotIn("vnc", serialized.lower())

    def test_rejects_missing_or_true_view_only_and_non_https_links(self) -> None:
        for payload in (
            _platform_payload(view_only=True),
            {
                key: value
                for key, value in _platform_payload().items()
                if key != "view_only"
            },
            _platform_payload(link=f"http://tinyhat.test/tinyhat/desktop/{SESSION_ID}"),
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                tool._safe_payload(payload)

    def test_platform_errors_do_not_echo_sensitive_details(self) -> None:
        with mock.patch.object(
            tool,
            "build_platform_client",
            side_effect=PlatformError("Bearer secret-value was rejected"),
        ):
            result = json.loads(tool.computer_desktop())

        self.assertEqual(result["error"], "computer_desktop_unavailable")
        self.assertNotIn("secret-value", json.dumps(result))

    def test_button_failure_preserves_browser_fallback(self) -> None:
        client = mock.Mock()
        client.post_json.return_value = _platform_payload()
        with (
            mock.patch.object(
                tool,
                "build_platform_client",
                return_value=(client, "gcloud"),
            ),
            mock.patch.object(tool, "_send_desktop_button", return_value=False),
        ):
            result = json.loads(tool.computer_desktop())

        self.assertEqual(result["link"], LINK)
        self.assertEqual(result["access_code"], "123456")
        self.assertFalse(result["telegram_button_sent"])

    def test_desktop_button_uses_native_mini_app_link(self) -> None:
        sent: dict[str, object] = {}

        def send_message(**kwargs: object) -> dict[str, bool]:
            sent.update(kwargs)
            return {"ok": True}

        created = tool._safe_payload(_platform_payload())
        with (
            mock.patch.object(
                root_tools,
                "_telegram_credentials",
                return_value=("token", "123"),
            ),
            mock.patch.object(
                root_tools,
                "_telegram_send_message",
                side_effect=send_message,
            ),
        ):
            self.assertTrue(tool._send_desktop_button(created))

        self.assertIn(LINK, str(sent["text"]))
        self.assertIn("123456", str(sent["text"]))
        self.assertIn("interactive", str(sent["text"]))
        self.assertNotIn("view-only", str(sent["text"]))
        self.assertEqual(
            sent["reply_markup"],
            {
                "inline_keyboard": [
                    [{"text": "Open desktop", "web_app": {"url": LINK}}]
                ]
            },
        )

    def test_desktop_button_failure_is_nonfatal(self) -> None:
        created = tool._safe_payload(_platform_payload())
        with mock.patch.object(
            root_tools,
            "_telegram_credentials",
            side_effect=ValueError("missing Telegram credentials"),
        ):
            self.assertFalse(tool._send_desktop_button(created))

    def test_skill_uses_user_language_and_marks_interactive(self) -> None:
        skill = (
            REPO_ROOT / "skills" / "tinyhat-computer-desktop" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("six-digit", skill)
        self.assertIn("interactive", skill)
        self.assertIn("open applications", skill)
        self.assertIn("session IDs", skill)
        self.assertIn("internal identifiers", skill)
        self.assertNotIn("port number", skill)


if __name__ == "__main__":
    unittest.main()
