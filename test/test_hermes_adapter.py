"""Hermes adapter smoke tests for the framework-neutral Tinyhat plugin."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT = REPO_ROOT.parent
sys.path.insert(0, str(PARENT))

import tinyhat  # noqa: E402
from tinyhat import tools  # noqa: E402


class FakeHermesContext:
    def __init__(self) -> None:
        self.tools: dict[str, dict] = {}
        self.commands: dict[str, dict] = {}
        self.skills: dict[str, Path] = {}

    def register_tool(self, **kwargs) -> None:
        self.tools[kwargs["name"]] = kwargs

    def register_command(self, **kwargs) -> None:
        self.commands[kwargs["name"]] = kwargs

    def register_skill(self, name: str, skill_md: Path) -> None:
        self.skills[name] = skill_md


class HermesAdapterTests(unittest.TestCase):
    def test_register_exposes_proof_tool_command_and_skill(self) -> None:
        ctx = FakeHermesContext()

        tinyhat.register(ctx)

        self.assertIn("tinyhat_plugin_version", ctx.tools)
        self.assertIn("tinyhat_tell_joke", ctx.tools)
        self.assertIn("tinyhat_plugin_version", ctx.commands)
        self.assertIn("tinyhat_joke", ctx.commands)
        self.assertIn("tinyhat-plugin-version", ctx.skills)
        self.assertIn("tinyhat-tell-joke", ctx.skills)
        self.assertTrue(ctx.skills["tinyhat-plugin-version"].is_file())
        self.assertTrue(ctx.skills["tinyhat-tell-joke"].is_file())

    def test_plugin_version_returns_live_manifest_version(self) -> None:
        payload = json.loads(tools.plugin_version())

        self.assertEqual(payload["schema"], "tinyhat_plugin_version_v1")
        self.assertEqual(payload["name"], "tinyhat")
        self.assertEqual(payload["version"], "0.20.2")

    def test_tell_joke_returns_stable_json(self) -> None:
        payload = json.loads(tools.tell_joke({"topic": "Hermes"}))

        self.assertEqual(payload["schema"], "tinyhat_tell_joke_v1")
        self.assertIn("Hermes", payload["joke"])

    def test_tell_joke_ignores_hermes_runtime_metadata(self) -> None:
        payload = json.loads(
            tools.tell_joke({"topic": "Hermes"}, task_id="task_123")
        )

        self.assertEqual(payload["schema"], "tinyhat_tell_joke_v1")
        self.assertIn("Hermes", payload["joke"])


if __name__ == "__main__":
    unittest.main()
