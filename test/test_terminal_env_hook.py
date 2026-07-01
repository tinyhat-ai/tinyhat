"""Tests for the Tinyhat Hermes terminal env hook."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))

from tinyhat.terminal_env_hook import install_terminal_env_reload_hook


class TerminalEnvHookTests(unittest.TestCase):
    def test_installs_shell_init_hook_without_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "home"
            home.mkdir()
            old_env = os.environ.copy()
            os.environ.clear()
            os.environ.update({"HOME": str(home)})
            try:
                result = install_terminal_env_reload_hook()
                hook_path = home / ".hermes" / "tinyhat" / "terminal-env.sh"
                config_path = home / ".hermes" / "config.yaml"
                hook_text = hook_path.read_text(encoding="utf-8")
                config_text = config_path.read_text(encoding="utf-8")
            finally:
                os.environ.clear()
                os.environ.update(old_env)

        self.assertTrue(result["installed"])
        self.assertIn("set -a", hook_text)
        self.assertIn("$HOME/.hermes/.env", hook_text)
        self.assertNotIn("API_KEY=", hook_text)
        self.assertIn("terminal:", config_text)
        self.assertIn("shell_init_files:", config_text)
        self.assertIn(str(hook_path), config_text)

    def test_preserves_existing_terminal_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "home"
            config_path = home / ".hermes" / "config.yaml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                "terminal:\n  backend: local\n  timeout: 180\n",
                encoding="utf-8",
            )
            old_env = os.environ.copy()
            os.environ.clear()
            os.environ.update({"HOME": str(home)})
            try:
                first = install_terminal_env_reload_hook()
                second = install_terminal_env_reload_hook()
                config_text = config_path.read_text(encoding="utf-8")
            finally:
                os.environ.clear()
                os.environ.update(old_env)

        self.assertTrue(first["config"]["updated"])
        self.assertFalse(second["config"]["updated"])
        self.assertIn("  backend: local", config_text)
        self.assertEqual(config_text.count("terminal-env.sh"), 1)


if __name__ == "__main__":
    unittest.main()
