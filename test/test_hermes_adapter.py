"""Hermes adapter smoke tests for the framework-neutral Tinyhat plugin."""

from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import tempfile
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
from tinyhat import context as tinyhat_context  # noqa: E402
from tinyhat import secret_handoff_worker  # noqa: E402


class FakeHermesContext:
    def __init__(self) -> None:
        self.tools: dict[str, dict] = {}
        self.commands: dict[str, dict] = {}
        self.skills: dict[str, Path] = {}
        self.hooks: dict[str, list] = {}

    def register_tool(self, **kwargs) -> None:
        self.tools[kwargs["name"]] = kwargs

    def register_command(self, name: str, handler, **kwargs) -> None:
        self.commands[name] = {"name": name, "handler": handler, **kwargs}

    def register_skill(self, name: str, skill_md: Path) -> None:
        self.skills[name] = skill_md

    def register_hook(self, name: str, handler) -> None:
        self.hooks.setdefault(name, []).append(handler)


class HermesAdapterTests(unittest.TestCase):
    def test_register_exposes_proof_tool_command_and_skill(self) -> None:
        ctx = FakeHermesContext()

        tinyhat.register(ctx)

        self.assertIn("tinyhat_plugin_version", ctx.tools)
        self.assertIn("tinyhat_tell_joke", ctx.tools)
        self.assertIn("tinyhat_private_secret_handoff", ctx.tools)
        self.assertIn("tinyhat_codex_auth", ctx.tools)
        self.assertIn("tinyhat-plugin-version", ctx.commands)
        self.assertIn("tinyhat-joke", ctx.commands)
        self.assertIn("tinyhat-secret", ctx.commands)
        self.assertIn("pre_llm_call", ctx.hooks)
        self.assertIn("tinyhat-plugin-version", ctx.skills)
        self.assertIn("tinyhat-tell-joke", ctx.skills)
        self.assertIn("tinyhat-private-secret", ctx.skills)
        self.assertIn("tinyhat-codex-auth", ctx.skills)
        self.assertIn("tinyhat-platform", ctx.skills)
        self.assertTrue(ctx.skills["tinyhat-plugin-version"].is_file())
        self.assertTrue(ctx.skills["tinyhat-tell-joke"].is_file())
        self.assertTrue(ctx.skills["tinyhat-private-secret"].is_file())
        self.assertTrue(ctx.skills["tinyhat-codex-auth"].is_file())
        self.assertTrue(ctx.skills["tinyhat-platform"].is_file())

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
        self.assertEqual(payload["version"], "0.20.10")

    def test_context_hook_injects_for_secret_requests(self) -> None:
        ctx = FakeHermesContext()
        tinyhat.register(ctx)

        injected = ctx.hooks["pre_llm_call"][0](
            user_message="I want to add my Exa API key",
            is_first_turn=False,
        )

        self.assertIsNotNone(injected)
        assert injected is not None
        self.assertIn("tinyhat_private_secret_handoff", injected["context"])
        self.assertIn("Do not ask the user to paste secrets", injected["context"])
        self.assertIn("/codex_auth", injected["context"])
        self.assertIn("tinyhat:tinyhat-codex-auth", injected["context"])

    def test_context_hook_injects_for_chatgpt_subscription_requests(self) -> None:
        examples = (
            "I want to connect you to my chatgpt account",
            "I want to use my codex subscription here instead of platform credits",
            "Please use my ChatGPT Pro plan",
            "Switch from platform credits to my own OpenAI paid access",
        )
        for user_message in examples:
            with self.subTest(user_message=user_message):
                injected = tinyhat_context.inject_tinyhat_context(
                    user_message=user_message,
                    is_first_turn=False,
                )
                self.assertIsNotNone(injected)
                assert injected is not None
                self.assertIn("tinyhat:tinyhat-codex-auth", injected["context"])
                self.assertIn("Do not ask a multiple-choice clarification", injected["context"])
                self.assertIn("call tinyhat_codex_auth once with action=prerequisite", injected["context"])
                self.assertIn("Do not send an extra text reply", injected["context"])
                self.assertIn("/codex_auth", injected["context"])
                self.assertIn("on its own line", injected["context"])

    def test_context_hook_injects_for_codex_device_code_confirmation(self) -> None:
        injected = tinyhat_context.inject_tinyhat_context(
            user_message="I enabled device code authorization for Codex",
            is_first_turn=False,
        )

        self.assertIsNotNone(injected)
        assert injected is not None
        self.assertIn("tinyhat_codex_auth", injected["context"])
        self.assertIn("/codex_auth", injected["context"])

    def test_codex_auth_skill_packages_prerequisite_screenshot(self) -> None:
        skill_md = REPO_ROOT / "skills" / "tinyhat-codex-auth" / "SKILL.md"
        screenshot = (
            REPO_ROOT
            / "skills"
            / "tinyhat-codex-auth"
            / "assets"
            / "chatgpt-enable-device-code-for-codex.png"
        )
        text = skill_md.read_text(encoding="utf-8")

        self.assertTrue(screenshot.is_file())
        self.assertGreater(screenshot.stat().st_size, 10_000)
        self.assertIn("For common natural-language requests, call `tinyhat_codex_auth` once", text)
        self.assertIn('{"action": "prerequisite"}', text)
        self.assertIn("caption is the user-facing reply.", text)
        self.assertIn("Keep `/codex_auth` on its own line", text)
        self.assertIn("Open `chatgpt.com`", text)
        self.assertIn("Secure sign in with ChatGPT", text)
        self.assertIn("Enable device code authorization for Codex", text)
        self.assertIn("Then come back here and tap:", text)
        self.assertIn("/codex_auth", text)
        self.assertIn("Do not call `tinyhat_codex_auth` twice", text)
        self.assertIn("Do not send an extra normal chat reply", text)
        self.assertIn('{"action": "start", "confirmed": true}', text)
        self.assertIn("tinyhat_codex_auth", text)
        self.assertIn("hermes_runtime.telegram_codex_auth start", text)

    def test_codex_auth_tool_sends_prerequisite_without_starting_auth(self) -> None:
        original_prerequisite = tools._send_codex_prerequisite
        original_start = tools._start_runtime_codex_auth
        start_calls = []
        try:
            tools._send_codex_prerequisite = lambda: {
                "ok": True,
                "mode": "photo",
            }
            tools._start_runtime_codex_auth = lambda: start_calls.append(True) or {
                "ok": True,
            }

            payload = json.loads(tools.codex_auth({}))
        finally:
            tools._send_codex_prerequisite = original_prerequisite
            tools._start_runtime_codex_auth = original_start

        self.assertEqual(payload["schema"], "tinyhat_codex_auth_start_v1")
        self.assertEqual(payload["status"], "waiting_for_confirmation")
        self.assertIs(payload["chat_response_required"], False)
        self.assertEqual(payload["prerequisite"]["mode"], "photo")
        self.assertNotIn("confirmation_choice", payload["prerequisite"])
        self.assertNotIn("message", payload)
        self.assertIn("/codex_auth", payload["next_user_action"])
        self.assertIn("Do not send any chat reply", payload["agent_instruction"])
        self.assertEqual(start_calls, [])

    def test_codex_auth_prerequisite_does_not_attach_reply_keyboard(self) -> None:
        original_credentials = tools._telegram_credentials
        original_send_photo = tools._telegram_send_photo
        captured: dict[str, object] = {}
        try:
            tools._telegram_credentials = lambda: ("token", "chat")

            def fake_send_photo(**kwargs):
                captured.update(kwargs)
                return {"ok": True}

            tools._telegram_send_photo = fake_send_photo

            payload = tools._send_codex_prerequisite()
        finally:
            tools._telegram_credentials = original_credentials
            tools._telegram_send_photo = original_send_photo

        self.assertTrue(payload["ok"])
        self.assertNotIn("confirmation_choice", payload)
        self.assertIn("/codex_auth", str(captured.get("caption")))
        self.assertNotIn("reply_markup", captured)

    def test_codex_auth_tool_refuses_start_without_confirmation(self) -> None:
        original_start = tools._start_runtime_codex_auth
        start_calls = []
        try:
            tools._start_runtime_codex_auth = lambda: start_calls.append(True) or {
                "ok": True,
            }

            payload = json.loads(tools.codex_auth({"action": "start"}))
        finally:
            tools._start_runtime_codex_auth = original_start

        self.assertEqual(payload["schema"], "tinyhat_codex_auth_start_v1")
        self.assertEqual(payload["status"], "waiting_for_confirmation")
        self.assertIn("Enable device code authorization", payload["message"])
        self.assertIn("/codex_auth", payload["message"])
        self.assertEqual(start_calls, [])

    def test_codex_auth_tool_starts_after_confirmation(self) -> None:
        original_prerequisite = tools._send_codex_prerequisite
        original_start = tools._start_runtime_codex_auth
        prerequisite_calls = []
        try:
            tools._send_codex_prerequisite = lambda: prerequisite_calls.append(True) or {
                "ok": True,
                "mode": "photo",
            }
            tools._start_runtime_codex_auth = lambda: {
                "ok": True,
                "returncode": 0,
                "stdout": "auth started",
                "stderr": "",
            }

            payload = json.loads(tools.codex_auth({"action": "start", "confirmed": True}))
        finally:
            tools._send_codex_prerequisite = original_prerequisite
            tools._start_runtime_codex_auth = original_start

        self.assertEqual(payload["schema"], "tinyhat_codex_auth_start_v1")
        self.assertEqual(payload["status"], "started")
        self.assertEqual(prerequisite_calls, [])
        self.assertTrue(payload["auth_start"]["ok"])

    def test_context_hook_injects_for_env_style_secret_names(self) -> None:
        for secret_name in (
            "EXA_API_KEY",
            "OPENROUTER_API_KEY",
            "GITHUB_TOKEN",
            "STRIPE_SECRET_KEY",
            "TAVILY_API_KEY",
            "FIRECRAWL_API_KEY",
        ):
            with self.subTest(secret_name=secret_name):
                injected = tinyhat_context.inject_tinyhat_context(
                    user_message=f"Please add {secret_name}",
                    is_first_turn=False,
                )
                self.assertIsNotNone(injected)

    def test_context_hook_skips_unrelated_later_turns(self) -> None:
        self.assertIsNone(
            tinyhat_context.inject_tinyhat_context(
                user_message="Tell me a short poem about the moon",
                is_first_turn=False,
            )
        )
        self.assertIsNone(
            tinyhat_context.inject_tinyhat_context(
                user_message="Write an author bio and estimate token count",
                is_first_turn=False,
            )
        )

    def test_context_hook_injects_on_first_turn(self) -> None:
        injected = tinyhat_context.inject_tinyhat_context(
            user_message="hello",
            is_first_turn=True,
        )

        self.assertIsNotNone(injected)
        assert injected is not None
        self.assertIn("Tinyhat-managed Computer", injected["context"])

    def test_tinyhat_secret_command_without_args_returns_usage(self) -> None:
        ctx = FakeHermesContext()
        tinyhat.register(ctx)

        reply = ctx.commands["tinyhat-secret"]["handler"]("")

        self.assertIn("/tinyhat_secret EXA_API_KEY", reply)
        self.assertNotIn("TINYHAT_SECRET", reply)

    def test_tell_joke_returns_stable_json(self) -> None:
        payload = json.loads(tools.tell_joke({"topic": "Hermes"}))

        self.assertEqual(payload["schema"], "tinyhat_tell_joke_v1")
        self.assertIn("Hermes", payload["joke"])

    def test_private_secret_handoff_returns_readable_confirmation(self) -> None:
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
        worker_calls: list[dict] = []
        original_worker = secret_handoff._start_worker_process
        try:
            secret_handoff.build_platform_client = lambda: (fake_client, "local_dev")
            secret_handoff._generate_key_pair = lambda: ("PRIVATE", "PUBLIC")
            secret_handoff._start_worker_process = lambda handoff, private_key_pem: worker_calls.append(
                {"handoff": handoff, "private_key_pem": private_key_pem}
            )

            reply = tools.private_secret_handoff(
                {
                    "name": "github_token",
                    "description": "GitHub access for repository tasks",
                    "expires_in_seconds": 600,
                }
            )
        finally:
            secret_handoff.build_platform_client = original_build
            secret_handoff._generate_key_pair = original_generate
            secret_handoff._start_worker_process = original_worker

        self.assertEqual(
            fake_client.path,
            "/hapi/v1/computers/local-dev/private-secret-handoffs/v1",
        )
        self.assertEqual(fake_client.payload["name"], "GITHUB_TOKEN")
        self.assertEqual(fake_client.payload["expires_in_seconds"], 300)
        self.assertEqual(worker_calls[0]["private_key_pem"], "PRIVATE")
        self.assertIn("I sent the secure Enter secret button", reply)
        self.assertIn("GITHUB_TOKEN", reply)
        self.assertIn("within about 5 minutes", reply)
        self.assertIn("never sees the plaintext", reply)
        self.assertNotIn("handoff", reply.lower())
        self.assertNotIn("Expires", reply)
        self.assertNotIn("waiting_for_user", reply)
        self.assertFalse(reply.strip().startswith("{"))

    def test_private_secret_handoff_infers_name_from_user_wording(self) -> None:
        class FakeClient:
            def post_json(self, path: str, payload: dict) -> dict:
                self.path = path
                self.payload = payload
                return {
                    "handoff_id": "sh_exa",
                    "status": "pending",
                    "secret_name": payload["name"],
                    "description": payload["description"],
                    "expires_at": "2026-06-29T12:00:00Z",
                    "poll_after_ms": 2000,
                }

        fake_client = FakeClient()
        original_build = secret_handoff.build_platform_client
        original_generate = secret_handoff._generate_key_pair
        original_worker = secret_handoff._start_worker_process
        try:
            secret_handoff.build_platform_client = lambda: (fake_client, "local_dev")
            secret_handoff._generate_key_pair = lambda: ("PRIVATE", "PUBLIC")
            secret_handoff._start_worker_process = lambda *_: None

            reply = tools.private_secret_handoff(
                {
                    "name": "TINYHAT_SECRET",
                    "description": "Exa API key for search research",
                }
            )
        finally:
            secret_handoff.build_platform_client = original_build
            secret_handoff._generate_key_pair = original_generate
            secret_handoff._start_worker_process = original_worker

        self.assertEqual(fake_client.payload["name"], "EXA_API_KEY")
        self.assertIn("EXA_API_KEY", reply)

    def test_private_secret_handoff_does_not_start_second_worker_for_existing_pending(
        self,
    ) -> None:
        class FakeClient:
            def post_json(self, path: str, payload: dict) -> dict:
                self.path = path
                self.payload = payload
                return {
                    "handoff_id": "sh_existing",
                    "existing_handoff": True,
                    "status": "pending",
                    "secret_name": payload["name"],
                    "description": payload["description"],
                    "expires_at": "2026-06-29T12:00:00Z",
                    "poll_after_ms": 2000,
                }

        fake_client = FakeClient()
        worker_calls: list[dict] = []
        original_build = secret_handoff.build_platform_client
        original_generate = secret_handoff._generate_key_pair
        original_worker = secret_handoff._start_worker_process
        try:
            secret_handoff.build_platform_client = lambda: (fake_client, "local_dev")
            secret_handoff._generate_key_pair = lambda: ("PRIVATE", "PUBLIC")
            secret_handoff._start_worker_process = lambda handoff, private_key_pem: worker_calls.append(
                {"handoff": handoff, "private_key_pem": private_key_pem}
            )

            reply = tools.private_secret_handoff(
                {
                    "name": "EXA_API_KEY",
                    "description": "Exa API key for search",
                }
            )
        finally:
            secret_handoff.build_platform_client = original_build
            secret_handoff._generate_key_pair = original_generate
            secret_handoff._start_worker_process = original_worker

        self.assertEqual(worker_calls, [])
        self.assertIn("EXA_API_KEY", reply)

    def test_private_secret_handoff_rejects_generic_unknown_name(self) -> None:
        with self.assertRaises(secret_handoff.SecretHandoffError) as exc:
            tools.private_secret_handoff(
                {
                    "name": "TINYHAT_SECRET",
                    "description": "generic credential",
                }
            )

        self.assertIn("specific", str(exc.exception))

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

    def test_private_secret_install_notifies_before_claim(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.claim_payloads: list[dict] = []

            def post_json(self, path: str, payload: dict) -> dict:
                events.append(("claim", payload.get("installed")))
                self.claim_payloads.append(payload)
                return {"status": "claimed"}

        events: list[tuple[str, object]] = []
        fake_client = FakeClient()
        original_decrypt = secret_handoff._decrypt_ciphertext
        original_set = secret_handoff._set_hermes_secret
        original_notice = secret_handoff._send_secret_available_notice
        original_restart = secret_handoff._restart_gateway_after_secret
        try:
            secret_handoff._decrypt_ciphertext = lambda *_: "super-secret-value"
            secret_handoff._set_hermes_secret = lambda name, value: events.append(
                ("set", name)
            )
            secret_handoff._send_secret_available_notice = lambda name: events.append(
                ("notice", name)
            ) or {"sent": True, "ok": True}
            secret_handoff._restart_gateway_after_secret = lambda: events.append(
                ("restart", True)
            ) or {"healthy": True}

            secret_handoff._install_submitted_secret(
                client=fake_client,
                platform_auth="local_dev",
                handoff_id="sh_test",
                private_key_pem="PRIVATE",
                state={
                    "secret_name": "EXA_API_KEY",
                    "ciphertext_payload": {"algorithm": "RSA-OAEP-256"},
                },
            )
        finally:
            secret_handoff._decrypt_ciphertext = original_decrypt
            secret_handoff._set_hermes_secret = original_set
            secret_handoff._send_secret_available_notice = original_notice
            secret_handoff._restart_gateway_after_secret = original_restart

        self.assertEqual(
            events,
            [
                ("set", "EXA_API_KEY"),
                ("notice", "EXA_API_KEY"),
                ("restart", True),
                ("claim", True),
            ],
        )
        self.assertEqual(
            fake_client.claim_payloads[-1],
            {"installed": True, "message": None},
        )
        self.assertNotIn("super-secret-value", json.dumps(fake_client.claim_payloads))

    def test_private_secret_save_ignores_worker_reload_failure(self) -> None:
        original_which = secret_handoff.shutil.which
        original_run = secret_handoff._run
        original_reload = secret_handoff._reload_hermes_env_current_process
        calls: list[dict[str, object]] = []

        try:
            secret_handoff.shutil.which = lambda name: (
                "/usr/bin/hermes" if name == "hermes" else None
            )
            secret_handoff._run = lambda args, **kwargs: calls.append(
                {"args": args, **kwargs}
            )
            secret_handoff._reload_hermes_env_current_process = (
                lambda *_: (_ for _ in ()).throw(RuntimeError("reload failed"))
            )

            secret_handoff._set_hermes_secret("EXA_API_KEY", "super-secret-value")
        finally:
            secret_handoff.shutil.which = original_which
            secret_handoff._run = original_run
            secret_handoff._reload_hermes_env_current_process = original_reload

        self.assertEqual(calls[0]["args"][:3], ["/usr/bin/hermes", "config", "set"])
        self.assertEqual(calls[0]["redactions"], ("super-secret-value",))

    def test_private_secret_restart_gateway_uses_runtime_stop_start(self) -> None:
        original_which = secret_handoff.shutil.which
        original_run = secret_handoff.subprocess.run
        calls: list[dict] = []

        def fake_run(args, **kwargs):
            calls.append({"args": args, **kwargs})
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout='{"healthy": true, "start": {"healthy": true}, "stop": {}}',
                stderr="",
            )

        try:
            secret_handoff.shutil.which = lambda name: "/usr/bin/hermes"
            secret_handoff.subprocess.run = fake_run

            result = secret_handoff._restart_gateway_after_secret()
        finally:
            secret_handoff.shutil.which = original_which
            secret_handoff.subprocess.run = original_run

        self.assertTrue(result["healthy"])
        self.assertEqual(calls[0]["args"][0], sys.executable)
        script = calls[0]["args"][2]
        self.assertIn("stop_hermes.run", script)
        self.assertIn("start_hermes.run", script)
        self.assertIn(
            "/opt/tinyhat-hermes-runtime",
            calls[0]["env"].get("PYTHONPATH", ""),
        )

    def test_private_secret_restart_gateway_rejects_bad_subprocess_results(self) -> None:
        original_which = secret_handoff.shutil.which
        original_run = secret_handoff.subprocess.run

        def assert_restart_error(completed: subprocess.CompletedProcess) -> None:
            secret_handoff.subprocess.run = lambda *_, **__: completed
            with self.assertRaises(secret_handoff.SecretHandoffError) as raised:
                secret_handoff._restart_gateway_after_secret()
            self.assertTrue(raised.exception.public_message)
            self.assertIn("Hermes saved the secret", raised.exception.public_message)

        try:
            secret_handoff.shutil.which = lambda name: "/usr/bin/hermes"
            assert_restart_error(
                subprocess.CompletedProcess(
                    args=["python"],
                    returncode=1,
                    stdout="",
                    stderr="gateway failed",
                )
            )
            assert_restart_error(
                subprocess.CompletedProcess(
                    args=["python"],
                    returncode=0,
                    stdout="not-json",
                    stderr="",
                )
            )
            assert_restart_error(
                subprocess.CompletedProcess(
                    args=["python"],
                    returncode=0,
                    stdout='{"healthy": false}',
                    stderr="",
                )
            )
        finally:
            secret_handoff.shutil.which = original_which
            secret_handoff.subprocess.run = original_run

    def test_private_secret_notice_is_plain_text_and_best_effort(self) -> None:
        original_credentials = tools._telegram_credentials
        original_send = tools._telegram_send_message
        sent_messages: list[str] = []

        try:
            tools._telegram_credentials = lambda: ("token", "chat")
            tools._telegram_send_message = lambda **kwargs: sent_messages.append(
                kwargs["text"]
            ) or {"ok": True}

            result = secret_handoff._send_secret_available_notice("EXA_API_KEY")
        finally:
            tools._telegram_credentials = original_credentials
            tools._telegram_send_message = original_send

        self.assertEqual(result, {"sent": True, "ok": True})
        self.assertIn("EXA_API_KEY is saved.", sent_messages[-1])
        self.assertNotIn("`", sent_messages[-1])

        original_credentials = tools._telegram_credentials
        try:
            tools._telegram_credentials = lambda: (_ for _ in ()).throw(
                RuntimeError("telegram unavailable")
            )

            failed = secret_handoff._send_secret_available_notice("EXA_API_KEY")
        finally:
            tools._telegram_credentials = original_credentials

        self.assertEqual(failed["sent"], False)
        self.assertEqual(failed["ok"], False)

    def test_worker_script_bootstraps_from_non_package_checkout(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "secret_handoff_worker.py"),
                "--help",
            ],
            cwd="/tmp",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--handoff-id", result.stdout)

    def test_live_worker_failure_message_is_sanitized(self) -> None:
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
        original_build = secret_handoff_worker.build_platform_client
        original_install = secret_handoff_worker._install_submitted_secret
        try:
            secret_handoff_worker.build_platform_client = lambda: (
                fake_client,
                "local_dev",
            )
            secret_handoff_worker._install_submitted_secret = lambda **_: (
                _ for _ in ()
            ).throw(
                secret_handoff.SecretHandoffError(
                    "worker echoed super-secret-value",
                    public_message="Hermes could not save this secret.",
                )
            )
            with tempfile.TemporaryDirectory(prefix="tinyhat-worker-test-") as temp_dir:
                key_path = Path(temp_dir) / "private.pem"
                key_path.write_text("PRIVATE", encoding="utf-8")

                with self.assertRaises(SystemExit):
                    secret_handoff_worker.run_worker(
                        handoff_id="sh_test",
                        key_path=key_path,
                    )
        finally:
            secret_handoff_worker.build_platform_client = original_build
            secret_handoff_worker._install_submitted_secret = original_install

        self.assertEqual(fake_client.claim_payloads[-1]["installed"], False)
        self.assertEqual(
            fake_client.claim_payloads[-1]["message"],
            "Hermes could not save this secret.",
        )
        self.assertNotIn("super-secret-value", json.dumps(fake_client.claim_payloads))

    def test_private_secret_save_reloads_current_process_from_hermes_config(self) -> None:
        original_secret = os.environ.get("EXA_API_KEY")
        try:
            os.environ.pop("EXA_API_KEY", None)
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_root = Path(temp_dir)
                env_file = temp_root / "hermes.env"
                package_link = temp_root / "tinyhat"
                package_link.symlink_to(REPO_ROOT, target_is_directory=True)
                bin_dir = temp_root / "bin"
                bin_dir.mkdir()
                fake_hermes = bin_dir / "hermes"
                fake_hermes.write_text(
                    """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

if sys.argv[1:3] != ["config", "set"] or len(sys.argv) != 5:
    sys.exit(2)

key = sys.argv[3]
value = sys.argv[4]
path = Path(os.environ["HERMES_ENV_FILE"])
path.parent.mkdir(parents=True, exist_ok=True)
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
escaped = value.replace("\\\\", "\\\\\\\\").replace('"', '\\\\"')
entry = f'{key}="{escaped}"'
updated = False
next_lines = []
for line in lines:
    clean_key, sep, _raw = line.partition("=")
    if sep and clean_key.strip() == key:
        next_lines.append(entry)
        updated = True
    else:
        next_lines.append(line)
if not updated:
    next_lines.append(entry)
path.write_text("\\n".join(next_lines).rstrip() + "\\n", encoding="utf-8")
path.chmod(0o600)
""",
                    encoding="utf-8",
                )
                fake_hermes.chmod(0o700)

                worker_env = dict(os.environ)
                worker_env.update(
                    {
                        "HOME": str(temp_root / "home"),
                        "HERMES_ENV_FILE": str(env_file),
                        "PATH": f"{bin_dir}{os.pathsep}{worker_env.get('PATH', '')}",
                        "PYTHONPATH": str(temp_root),
                    }
                )
                worker = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        (
                            "import os; "
                            "from tinyhat.secret_handoff import _set_hermes_secret; "
                            "_set_hermes_secret('EXA_API_KEY', 'test-secret-value'); "
                            "print('set' if os.environ.get('EXA_API_KEY') "
                            "== 'test-secret-value' else 'missing')"
                        ),
                    ],
                    cwd="/tmp",
                    env=worker_env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )

                self.assertEqual(worker.returncode, 0, worker.stderr)
                self.assertNotIn("test-secret-value", worker.stdout + worker.stderr)
                self.assertEqual(worker.stdout.strip(), "set")
                self.assertNotEqual(os.environ.get("EXA_API_KEY"), "test-secret-value")
                self.assertIn('EXA_API_KEY="test-secret-value"', env_file.read_text())
        finally:
            if original_secret is None:
                os.environ.pop("EXA_API_KEY", None)
            else:
                os.environ["EXA_API_KEY"] = original_secret

    def test_private_secret_save_uses_hermes_env_writer_for_secret_key_names(self) -> None:
        original_secret = os.environ.get("STRIPE_SECRET_KEY")
        try:
            os.environ.pop("STRIPE_SECRET_KEY", None)
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_root = Path(temp_dir)
                env_file = temp_root / "hermes.env"
                package_link = temp_root / "tinyhat"
                package_link.symlink_to(REPO_ROOT, target_is_directory=True)
                bin_dir = temp_root / "bin"
                venv_bin = temp_root / "hermes-agent" / "venv" / "bin"
                bin_dir.mkdir()
                venv_bin.mkdir(parents=True)

                fake_python = venv_bin / "python"
                fake_python.write_text(
                    f"""#!{sys.executable}
import os
import sys
from pathlib import Path

key = sys.argv[-1]
value = sys.stdin.read()
path = Path(os.environ["HERMES_ENV_FILE"])
path.parent.mkdir(parents=True, exist_ok=True)
escaped = value.replace("\\\\", "\\\\\\\\").replace('"', '\\\\"')
path.write_text(f'{{key}}="{{escaped}}"\\n', encoding="utf-8")
path.chmod(0o600)
""",
                    encoding="utf-8",
                )
                fake_python.chmod(0o700)
                fake_console = venv_bin / "hermes"
                fake_console.write_text(f"#!{fake_python}\n", encoding="utf-8")
                fake_console.chmod(0o700)
                fake_wrapper = bin_dir / "hermes"
                fake_wrapper.write_text(
                    f'#!/bin/sh\nexec "{fake_console}" "$@"\n',
                    encoding="utf-8",
                )
                fake_wrapper.chmod(0o700)

                worker_env = dict(os.environ)
                worker_env.update(
                    {
                        "HOME": str(temp_root / "home"),
                        "HERMES_ENV_FILE": str(env_file),
                        "PATH": f"{bin_dir}{os.pathsep}{worker_env.get('PATH', '')}",
                        "PYTHONPATH": str(temp_root),
                    }
                )
                worker = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        (
                            "import os; "
                            "from tinyhat.secret_handoff import _set_hermes_secret; "
                            "_set_hermes_secret('STRIPE_SECRET_KEY', "
                            "'test-secret-value'); "
                            "print('set' if os.environ.get('STRIPE_SECRET_KEY') "
                            "== 'test-secret-value' else 'missing')"
                        ),
                    ],
                    cwd="/tmp",
                    env=worker_env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )

                self.assertEqual(worker.returncode, 0, worker.stderr)
                self.assertNotIn("test-secret-value", worker.stdout + worker.stderr)
                self.assertEqual(worker.stdout.strip(), "set")
                self.assertNotEqual(
                    os.environ.get("STRIPE_SECRET_KEY"),
                    "test-secret-value",
                )
                self.assertIn(
                    'STRIPE_SECRET_KEY="test-secret-value"',
                    env_file.read_text(encoding="utf-8"),
                )
        finally:
            if original_secret is None:
                os.environ.pop("STRIPE_SECRET_KEY", None)
            else:
                os.environ["STRIPE_SECRET_KEY"] = original_secret

    def test_tell_joke_ignores_hermes_runtime_metadata(self) -> None:
        payload = json.loads(
            tools.tell_joke({"topic": "Hermes"}, task_id="task_123")
        )

        self.assertEqual(payload["schema"], "tinyhat_tell_joke_v1")
        self.assertIn("Hermes", payload["joke"])


if __name__ == "__main__":
    unittest.main()
