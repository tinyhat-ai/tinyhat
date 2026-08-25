"""Tests for the view-only Computer desktop capability."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))
from package_support import load_local_tinyhat  # noqa: E402

load_local_tinyhat(REPO_ROOT)

from tinyhat.capabilities.computer_desktop import tool  # noqa: E402


class ComputerDesktopToolTests(unittest.TestCase):
    def test_creates_owner_connection_without_transport_details(self) -> None:
        original = tool.build_platform_client
        original_send = tool._send_desktop_button
        calls: list[tuple[str, dict[str, object]]] = []
        sent: list[dict[str, object]] = []

        class FakeClient:
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                calls.append((path, payload))
                return {
                    "schema_version": "v1",
                    "session_id": "dsk_012345678901234567890123",
                    "link": "https://tinyhat.test/tinyhat/desktop/dsk_012345678901234567890123",
                    "access_code": "123456",
                    "expires_at": "2026-08-25T12:00:00Z",
                    "view_only": True,
                    "tailnet_ip": "100.64.0.1",
                    "vnc_password": "must-not-leak",
                }

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
        self.assertTrue(result["telegram_button_sent"])
        self.assertEqual(sent[0]["link"], result["link"])
        serialized = json.dumps(result)
        self.assertNotIn("tailnet", serialized)
        self.assertNotIn("vnc", serialized.lower())

    def test_skill_uses_user_language_and_marks_view_only(self) -> None:
        skill = (
            REPO_ROOT / "skills" / "tinyhat-computer-desktop" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("six-digit", skill)
        self.assertIn("view-only", skill)
        self.assertIn("session IDs", skill)
        self.assertIn("internal identifiers", skill)
        self.assertNotIn("port number", skill)


if __name__ == "__main__":
    unittest.main()
