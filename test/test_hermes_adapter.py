"""Hermes adapter smoke tests for the framework-neutral Tinyhat plugin."""

from __future__ import annotations

import json
import importlib.util
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
        self.assertEqual(payload["version"], "0.20.11")

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

    def test_worker_reloads_hermes_before_claiming_secret_saved(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.claim_payloads: list[dict] = []

            def post_json(self, path: str, payload: dict) -> dict:
                self.claim_payloads.append(payload)
                return {"status": "claimed"}

        calls: list[str] = []
        original_decrypt = secret_handoff._decrypt_ciphertext
        original_set = secret_handoff._set_hermes_secret
        original_reload = secret_handoff._reload_hermes_gateway_after_secret
        fake_client = FakeClient()
        try:
            secret_handoff._decrypt_ciphertext = lambda *_: "super-secret-value"
            secret_handoff._set_hermes_secret = lambda *_: calls.append("set")
            secret_handoff._reload_hermes_gateway_after_secret = lambda: calls.append(
                "reload"
            )

            secret_handoff._install_submitted_secret(
                client=fake_client,
                platform_auth="local_dev",
                handoff_id="sh_test",
                private_key_pem="PRIVATE",
                state={
                    "secret_name": "EXA_API_KEY",
                    "ciphertext_payload": {
                        "algorithm": "RSA-OAEP-256",
                        "ciphertext_b64": "ignored",
                    },
                },
            )
        finally:
            secret_handoff._decrypt_ciphertext = original_decrypt
            secret_handoff._set_hermes_secret = original_set
            secret_handoff._reload_hermes_gateway_after_secret = original_reload

        self.assertEqual(calls, ["set", "reload"])
        self.assertEqual(fake_client.claim_payloads[-1]["installed"], True)

    def test_worker_does_not_claim_success_when_reload_fails(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.claim_payloads: list[dict] = []

            def get_json(self, path: str) -> dict:
                return {
                    "status": "submitted",
                    "secret_name": "EXA_API_KEY",
                    "ciphertext_payload": {
                        "algorithm": "RSA-OAEP-256",
                        "ciphertext_b64": "ignored",
                    },
                }

            def post_json(self, path: str, payload: dict) -> dict:
                self.claim_payloads.append(payload)
                return {"status": "failed"}

        fake_client = FakeClient()
        original_decrypt = secret_handoff._decrypt_ciphertext
        original_set = secret_handoff._set_hermes_secret
        original_reload = secret_handoff._reload_hermes_gateway_after_secret
        try:
            secret_handoff._decrypt_ciphertext = lambda *_: "super-secret-value"
            secret_handoff._set_hermes_secret = lambda *_: None
            secret_handoff._reload_hermes_gateway_after_secret = lambda: (
                _ for _ in ()
            ).throw(
                secret_handoff.SecretHandoffError(
                    "reload output mentioned super-secret-value",
                    public_message=(
                        "Secret saved, but I could not reload Hermes. Send /restart "
                        "before using it."
                    ),
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
            secret_handoff._reload_hermes_gateway_after_secret = original_reload

        self.assertEqual(fake_client.claim_payloads[-1]["installed"], False)
        self.assertEqual(
            fake_client.claim_payloads[-1]["message"],
            "Secret saved, but I could not reload Hermes. Send /restart before using it.",
        )
        self.assertNotIn("super-secret-value", json.dumps(fake_client.claim_payloads))

    def test_gateway_log_failure_scan_ignores_old_failures(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tinyhat-log-test-") as temp_dir:
            log_path = Path(temp_dir) / "gateway.log"
            log_path.write_text(
                "old adapter creation failed\n",
                encoding="utf-8",
            )
            offset = log_path.stat().st_size
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("new start is healthy\n")

            self.assertFalse(
                secret_handoff._gateway_log_has_adapter_failure(
                    log_path,
                    since_byte=offset,
                )
            )

            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("platform 'telegram' requirements not met\n")

            self.assertTrue(
                secret_handoff._gateway_log_has_adapter_failure(
                    log_path,
                    since_byte=offset,
                )
            )

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

    def test_tell_joke_ignores_hermes_runtime_metadata(self) -> None:
        payload = json.loads(
            tools.tell_joke({"topic": "Hermes"}, task_id="task_123")
        )

        self.assertEqual(payload["schema"], "tinyhat_tell_joke_v1")
        self.assertIn("Hermes", payload["joke"])


if __name__ == "__main__":
    unittest.main()
