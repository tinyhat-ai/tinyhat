"""Hermes adapter smoke tests for the framework-neutral Tinyhat plugin."""

from __future__ import annotations

import json
import importlib.util
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT = REPO_ROOT.parent
sys.path.insert(0, str(PARENT))

if REPO_ROOT.name != "tinyhat":
    spec = importlib.util.spec_from_file_location(
        "tinyhat",
        REPO_ROOT / "__init__.py",
        submodule_search_locations=[str(REPO_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load local tinyhat package for tests.")
    tinyhat = importlib.util.module_from_spec(spec)
    sys.modules["tinyhat"] = tinyhat
    spec.loader.exec_module(tinyhat)
else:
    import tinyhat  # noqa: E402

from tinyhat import secret_handoff, tools  # noqa: E402


class FakeHermesContext:
    def __init__(self) -> None:
        self.tools: dict[str, dict] = {}
        self.commands: dict[str, dict] = {}
        self.skills: dict[str, Path] = {}

    def register_tool(self, **kwargs) -> None:
        self.tools[kwargs["name"]] = kwargs

    def register_command(self, name: str, handler, **kwargs) -> None:
        self.commands[name] = {"name": name, "handler": handler, **kwargs}

    def register_skill(self, name: str, skill_md: Path) -> None:
        self.skills[name] = skill_md


class HermesAdapterTests(unittest.TestCase):
    def test_register_exposes_proof_tool_command_and_skill(self) -> None:
        ctx = FakeHermesContext()

        tinyhat.register(ctx)

        self.assertIn("tinyhat_plugin_version", ctx.tools)
        self.assertIn("tinyhat_tell_joke", ctx.tools)
        self.assertIn("tinyhat_private_secret_handoff", ctx.tools)
        self.assertIn("tinyhat-plugin-version", ctx.commands)
        self.assertIn("tinyhat-joke", ctx.commands)
        self.assertIn("tinyhat-secret", ctx.commands)
        self.assertIn("tinyhat-plugin-version", ctx.skills)
        self.assertIn("tinyhat-tell-joke", ctx.skills)
        self.assertIn("tinyhat-private-secret", ctx.skills)
        self.assertTrue(ctx.skills["tinyhat-plugin-version"].is_file())
        self.assertTrue(ctx.skills["tinyhat-tell-joke"].is_file())
        self.assertTrue(ctx.skills["tinyhat-private-secret"].is_file())

    def test_registered_commands_match_telegram_dispatch_names(self) -> None:
        ctx = FakeHermesContext()

        tinyhat.register(ctx)

        for telegram_name in (
            "tinyhat_joke",
            "tinyhat_plugin_version",
            "tinyhat_secret",
        ):
            hermes_dispatch_name = telegram_name.replace("_", "-")
            self.assertIn(hermes_dispatch_name, ctx.commands)

    def test_plugin_version_returns_live_manifest_version(self) -> None:
        payload = json.loads(tools.plugin_version())

        self.assertEqual(payload["schema"], "tinyhat_plugin_version_v1")
        self.assertEqual(payload["name"], "tinyhat")
        self.assertEqual(payload["version"], "0.20.4")

    def test_tell_joke_returns_stable_json(self) -> None:
        payload = json.loads(tools.tell_joke({"topic": "Hermes"}))

        self.assertEqual(payload["schema"], "tinyhat_tell_joke_v1")
        self.assertIn("Hermes", payload["joke"])

    def test_private_secret_handoff_returns_secure_button_payload(self) -> None:
        class FakeClient:
            def post_json(self, path: str, payload: dict) -> dict:
                self.path = path
                self.payload = payload
                return {
                    "handoff_id": "sh_test",
                    "status": "pending",
                    "secret_name": payload["name"],
                    "description": payload["description"],
                    "mini_app_url": "https://example.test/tinyhat/miniapp/private-secrets/sh_test",
                    "button_text": "Enter secret",
                    "telegram_button": {
                        "text": "Enter secret",
                        "web_app": {
                            "url": "https://example.test/tinyhat/miniapp/private-secrets/sh_test"
                        },
                    },
                    "expires_at": "2026-06-29T12:00:00Z",
                    "poll_after_ms": 2000,
                }

        fake_client = FakeClient()
        original_build = secret_handoff.build_platform_client
        original_generate = secret_handoff._generate_key_pair
        original_worker = secret_handoff._poll_and_install_secret
        try:
            secret_handoff.build_platform_client = lambda: (fake_client, "local_dev")
            secret_handoff._generate_key_pair = lambda: ("PRIVATE", "PUBLIC")
            secret_handoff._poll_and_install_secret = lambda **_: None

            payload = json.loads(
                tools.private_secret_handoff(
                    {
                        "name": "github_token",
                        "description": "GitHub access for repository tasks",
                    }
                )
            )
        finally:
            secret_handoff.build_platform_client = original_build
            secret_handoff._generate_key_pair = original_generate
            secret_handoff._poll_and_install_secret = original_worker

        self.assertEqual(
            fake_client.path,
            "/hapi/v1/computers/local-dev/private-secret-handoffs/v1",
        )
        self.assertEqual(fake_client.payload["name"], "GITHUB_TOKEN")
        self.assertEqual(payload["schema"], "tinyhat_private_secret_handoff_v1")
        self.assertEqual(payload["status"], "waiting_for_user")
        self.assertEqual(payload["button_text"], "Enter secret")
        self.assertIn("web_app", payload["telegram_button"])

    def test_worker_claim_failure_message_is_sanitized(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.claim_payloads: list[dict] = []

            def get_json(self, path: str) -> dict:
                return {
                    "status": "submitted",
                    "secret_name": "PRIVATE_TOKEN",
                    "ciphertext_payload": {"algorithm": "RSA-OAEP-256"},
                }

            def post_json(self, path: str, payload: dict) -> dict:
                self.claim_payloads.append(payload)
                return {"status": "failed"}

        fake_client = FakeClient()
        original_decrypt = secret_handoff._decrypt_ciphertext
        original_set = secret_handoff._set_hermes_secret
        try:
            secret_handoff._decrypt_ciphertext = lambda *_: "super-secret-value"
            secret_handoff._set_hermes_secret = lambda *_: (_ for _ in ()).throw(
                secret_handoff.SecretHandoffError(
                    "hermes echoed super-secret-value",
                    public_message="Hermes could not save this secret.",
                )
            )

            secret_handoff._poll_and_install_secret(
                client=fake_client,
                platform_auth="local_dev",
                handoff={
                    "handoff_id": "sh_test",
                    "expires_at": "2999-01-01T00:00:00Z",
                    "poll_after_ms": 1,
                },
                private_key_pem="PRIVATE",
            )
        finally:
            secret_handoff._decrypt_ciphertext = original_decrypt
            secret_handoff._set_hermes_secret = original_set

        self.assertEqual(fake_client.claim_payloads[-1]["installed"], False)
        self.assertEqual(
            fake_client.claim_payloads[-1]["message"],
            "Hermes could not save this secret.",
        )
        self.assertNotIn("super-secret-value", json.dumps(fake_client.claim_payloads))

    def test_tell_joke_ignores_hermes_runtime_metadata(self) -> None:
        payload = json.loads(
            tools.tell_joke({"topic": "Hermes"}, task_id="task_123")
        )

        self.assertEqual(payload["schema"], "tinyhat_tell_joke_v1")
        self.assertIn("Hermes", payload["joke"])


if __name__ == "__main__":
    unittest.main()
