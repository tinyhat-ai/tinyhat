"""Hermes adapter smoke tests for the framework-neutral Tinyhat plugin."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib import error

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
    import tinyhat

from tinyhat import context as tinyhat_context  # noqa: E402
from tinyhat import (  # noqa: E402
    credentials,
    platform,
    schemas,
    secret_handoff,
    secret_handoff_worker,
    slack_connection,
    slack_disconnect,
    slack_disconnect_worker,
    tools,
)


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
    def setUp(self) -> None:
        # Isolate the durable funding-reminder marker from the real Hermes
        # home so tests never write outside their sandbox and each test
        # starts un-reminded.
        self._hermes_home = tempfile.TemporaryDirectory(prefix="tinyhat-hermes-home-")
        self._original_hermes_home = os.environ.get("TINYHAT_HERMES_HOME")
        os.environ["TINYHAT_HERMES_HOME"] = self._hermes_home.name

    def tearDown(self) -> None:
        if self._original_hermes_home is None:
            os.environ.pop("TINYHAT_HERMES_HOME", None)
        else:
            os.environ["TINYHAT_HERMES_HOME"] = self._original_hermes_home
        self._hermes_home.cleanup()

    def _reset_funding_marker(self) -> None:
        """Re-arm the once-per-Computer marker inside one test method."""
        marker = Path(self._hermes_home.name) / "tinyhat-funding-reminder-shown"
        if marker.exists():
            marker.unlink()

    def test_register_exposes_proof_tool_command_and_skill(self) -> None:
        ctx = FakeHermesContext()

        tinyhat.register(ctx)

        self.assertIn("tinyhat_plugin_version", ctx.tools)
        self.assertIn("tinyhat_get_platform_status", ctx.tools)
        self.assertIn("tinyhat_hats", ctx.tools)
        self.assertIn("tinyhat_tell_joke", ctx.tools)
        self.assertIn("tinyhat_skill_catalog", ctx.tools)
        self.assertIn("tinyhat_private_secret_handoff", ctx.tools)
        self.assertIn("tinyhat_slack_connect", ctx.tools)
        self.assertIn("tinyhat_slack_disconnect", ctx.tools)
        self.assertIn("tinyhat_credentials", ctx.tools)
        self.assertIn("tinyhat_codex_auth", ctx.tools)
        self.assertIn("tinyhat_plugin_update", ctx.tools)
        self.assertIn("tinyhat-plugin-version", ctx.commands)
        self.assertIn("tinyhat-joke", ctx.commands)
        self.assertIn("tinyhat-secret", ctx.commands)
        self.assertIn("pre_llm_call", ctx.hooks)
        self.assertIn("tinyhat-plugin-version", ctx.skills)
        self.assertIn("tinyhat-tell-joke", ctx.skills)
        self.assertIn("tinyhat-skill-catalog", ctx.skills)
        self.assertIn("tinyhat-skill-authoring", ctx.skills)
        self.assertIn("tinyhat-private-secret", ctx.skills)
        self.assertIn("tinyhat-slack", ctx.skills)
        self.assertIn("tinyhat-credentials", ctx.skills)
        self.assertIn("tinyhat-codex-auth", ctx.skills)
        self.assertIn("tinyhat-plugin-update", ctx.skills)
        self.assertIn("tinyhat-platform", ctx.skills)
        self.assertIn("tinyhat-privacy", ctx.skills)
        self.assertIn("hat-authoring", ctx.skills)
        self.assertTrue(ctx.skills["tinyhat-plugin-version"].is_file())
        self.assertTrue(ctx.skills["tinyhat-tell-joke"].is_file())
        self.assertTrue(ctx.skills["tinyhat-skill-catalog"].is_file())
        self.assertTrue(ctx.skills["tinyhat-skill-authoring"].is_file())
        self.assertTrue(ctx.skills["tinyhat-private-secret"].is_file())
        self.assertTrue(ctx.skills["tinyhat-slack"].is_file())
        self.assertTrue(ctx.skills["tinyhat-credentials"].is_file())
        self.assertTrue(ctx.skills["tinyhat-codex-auth"].is_file())
        self.assertTrue(ctx.skills["tinyhat-plugin-update"].is_file())
        self.assertTrue(ctx.skills["tinyhat-platform"].is_file())
        self.assertTrue(ctx.skills["tinyhat-privacy"].is_file())
        self.assertTrue(ctx.skills["hat-authoring"].is_file())

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

    def test_registered_tool_schemas_are_agent_actionable(self) -> None:
        self.assertEqual(schemas.TINYHAT_PLUGIN_VERSION_SCHEMA["properties"], {})
        self.assertEqual(schemas.TINYHAT_PLUGIN_VERSION_SCHEMA["required"], [])
        self.assertEqual(schemas.TINYHAT_GET_PLATFORM_STATUS_SCHEMA["properties"], {})
        self.assertEqual(schemas.TINYHAT_GET_PLATFORM_STATUS_SCHEMA["required"], [])
        self.assertFalse(schemas.TINYHAT_GET_PLATFORM_STATUS_SCHEMA["additionalProperties"])
        hats_schema = schemas.TINYHAT_HATS_SCHEMA
        self.assertEqual(hats_schema["required"], ["action"])
        self.assertEqual(
            hats_schema["properties"]["action"]["enum"],
            [
                "create",
                "list",
                "get",
                "update",
                "delete",
                "put_file",
                "define_credential",
                "configure_credentials",
                "list_credentials",
                "remove_credential",
            ],
        )
        self.assertIn("permanently deletes", hats_schema["description"])
        self.assertIn(
            "delete",
            hats_schema["properties"]["identifier"]["description"],
        )
        self.assertIn(
            "permanently delete this exact Hat",
            hats_schema["properties"]["confirmed"]["description"],
        )
        self.assertIn(
            "optional replacement audience",
            hats_schema["properties"]["customer_email"]["description"],
        )
        self.assertIn(
            "owner namespace stays server-controlled",
            hats_schema["properties"]["new_key"]["description"],
        )
        self.assertFalse(hats_schema["additionalProperties"])
        self.assertEqual(schemas.TINYHAT_TELL_JOKE_SCHEMA["properties"], {})
        self.assertEqual(schemas.TINYHAT_TELL_JOKE_SCHEMA["required"], [])
        self.assertEqual(schemas.TINYHAT_SKILL_CATALOG_SCHEMA["properties"], {})
        self.assertEqual(schemas.TINYHAT_SKILL_CATALOG_SCHEMA["required"], [])

        secret_schema = schemas.TINYHAT_PRIVATE_SECRET_HANDOFF_SCHEMA
        self.assertEqual(secret_schema["required"], ["name", "description"])
        self.assertFalse(secret_schema["additionalProperties"])
        self.assertIn("EXA_API_KEY", secret_schema["properties"]["name"]["description"])
        self.assertIn(
            "human-readable",
            secret_schema["properties"]["description"]["description"],
        )

        codex_schema = schemas.TINYHAT_CODEX_AUTH_SCHEMA
        self.assertEqual(codex_schema["required"], ["action"])
        self.assertFalse(codex_schema["additionalProperties"])
        self.assertEqual(
            codex_schema["properties"]["action"]["enum"],
            ["prerequisite", "start", "status", "log", "limits"],
        )
        self.assertIn("confirmed", codex_schema["properties"])
        self.assertNotIn("secret_name", secret_schema["properties"])
        self.assertNotIn("env_var", secret_schema["properties"])
        self.assertNotIn("key_name", secret_schema["properties"])
        slack_schema = schemas.TINYHAT_SLACK_CONNECT_SCHEMA
        self.assertEqual(slack_schema["properties"], {})
        self.assertEqual(slack_schema["required"], [])
        self.assertFalse(slack_schema["additionalProperties"])
        slack_disconnect_schema = schemas.TINYHAT_SLACK_DISCONNECT_SCHEMA
        self.assertEqual(slack_disconnect_schema["properties"], {})
        self.assertEqual(slack_disconnect_schema["required"], [])
        self.assertFalse(slack_disconnect_schema["additionalProperties"])

        credentials_schema = schemas.TINYHAT_CREDENTIALS_SCHEMA
        self.assertEqual(credentials_schema["required"], ["action"])
        self.assertFalse(credentials_schema["additionalProperties"])
        self.assertEqual(
            credentials_schema["properties"]["action"]["enum"],
            ["list", "remove"],
        )

        update_schema = schemas.TINYHAT_PLUGIN_UPDATE_SCHEMA
        self.assertEqual(update_schema["required"], ["action"])
        self.assertFalse(update_schema["additionalProperties"])
        self.assertEqual(update_schema["properties"]["action"]["enum"], ["status", "update"])
        self.assertIn("confirmed", update_schema["properties"])
        self.assertIn("restart_gateway", update_schema["properties"])

    def test_plugin_version_returns_live_manifest_version(self) -> None:
        payload = json.loads(tools.plugin_version())

        self.assertEqual(payload["schema"], "tinyhat_plugin_version_v1")
        self.assertEqual(payload["name"], "tinyhat")
        self.assertEqual(payload["version"], "0.23.0")

    def test_platform_status_uses_attested_computer_endpoint(self) -> None:
        original_build = tools.build_platform_client
        paths: list[str] = []

        class FakePlatformClient:
            def get_json(self, path: str) -> dict[str, object]:
                paths.append(path)
                return {
                    "computer_id": 5359,
                    "state": "active",
                    "assigned": True,
                    "package_inventory": {"plugin": {"version": "0.23.0"}},
                }

        try:
            tools.build_platform_client = lambda: (FakePlatformClient(), "gcloud")
            payload = json.loads(tools.get_platform_status(task_id="smoke-task"))
        finally:
            tools.build_platform_client = original_build

        self.assertEqual(paths, ["/hapi/v1/computers/me/platform-status"])
        self.assertEqual(payload["computer_id"], 5359)
        self.assertEqual(payload["state"], "active")
        self.assertTrue(payload["assigned"])
        self.assertEqual(payload["package_inventory"]["plugin"]["version"], "0.23.0")

    def test_platform_status_returns_structured_platform_error(self) -> None:
        original_build = tools.build_platform_client

        def fail_build():
            raise tools.PlatformError("TINYHAT_PLATFORM_URL is not configured")

        try:
            tools.build_platform_client = fail_build
            payload = json.loads(tools.get_platform_status())
        finally:
            tools.build_platform_client = original_build

        self.assertEqual(payload["schema"], "tinyhat_tool_error_v1")
        self.assertEqual(payload["tool"], "tinyhat_get_platform_status")
        self.assertEqual(payload["error"], "platform_status_unavailable")

    def test_skill_catalog_lists_qualified_names_and_aliases(self) -> None:
        payload = json.loads(tools.skill_catalog())

        self.assertEqual(payload["schema"], "tinyhat_skill_catalog_v1")
        self.assertEqual(payload["plugin"]["name"], "tinyhat")
        self.assertEqual(payload["plugin"]["version"], "0.23.0")
        by_name = {skill["name"]: skill for skill in payload["skills"]}
        self.assertEqual(
            by_name["tinyhat-codex-auth"]["qualified_name"],
            "tinyhat:tinyhat-codex-auth",
        )
        self.assertIn("tinyhat-codex-auth", by_name["tinyhat-codex-auth"]["aliases"])
        self.assertEqual(
            by_name["tinyhat-plugin-update"]["qualified_name"],
            "tinyhat:tinyhat-plugin-update",
        )
        self.assertEqual(
            by_name["tinyhat-privacy"]["qualified_name"],
            "tinyhat:tinyhat-privacy",
        )
        self.assertIn("tinyhat-privacy", by_name["tinyhat-privacy"]["aliases"])
        self.assertEqual(
            by_name["tinyhat-skill-authoring"]["qualified_name"],
            "tinyhat:tinyhat-skill-authoring",
        )
        self.assertIn(
            "trigger boundaries",
            by_name["tinyhat-skill-authoring"]["purpose"],
        )
        manager_purpose = by_name["tinyhat-google-workspace-app-manager"]["purpose"]
        self.assertIn("only the pinned Google Workspace CLI app", manager_purpose)
        self.assertIn("Hermes supplies the native operation skill", manager_purpose)
        self.assertNotIn("operation skills", manager_purpose)
        self.assertIn("qualified names", payload["lookup_rule"])

    def test_skill_authoring_playbook_enforces_portable_bounds(self) -> None:
        skill_md = REPO_ROOT / "skills" / "tinyhat-skill-authoring" / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")

        self.assertIn("1-64 lowercase letters", text)
        self.assertIn("at most 1,024 characters", text)
        self.assertIn("should not trigger", text)
        self.assertIn("about 200 lines and 2,000 tokens", text)
        self.assertIn("500 lines or about 5,000 tokens", text)
        self.assertIn("progressive-disclosure", text)
        self.assertLessEqual(len(text.splitlines()), 200)

    def test_credentials_list_returns_only_safe_metadata(self) -> None:
        paths: list[str] = []

        class FakePlatformClient:
            def get_json(self, path: str) -> dict[str, object]:
                paths.append(path)
                return {
                    "schema": "tinyhat_private_credentials_v1",
                    "credentials": [
                        {
                            "handoff_id": "sh_exa",
                            "name": "EXA_API_KEY",
                            "description": "Search API credential",
                            "value_available": False,
                        }
                    ],
                    "value_note": "Values live only on the Computer.",
                }

        with mock.patch.object(
            credentials,
            "build_platform_client",
            return_value=(FakePlatformClient(), "local_dev"),
        ):
            payload = json.loads(credentials.credentials({"action": "list", "query": "search API"}))

        self.assertEqual(
            paths,
            ["/hapi/v1/computers/local-dev/private-credentials/v1?q=search+API"],
        )
        self.assertEqual(payload["credentials"][0]["name"], "EXA_API_KEY")
        self.assertIs(payload["credentials"][0]["value_available"], False)
        self.assertNotIn("value", payload["credentials"][0])

    def test_credentials_remove_sends_one_generation_bound_request(self) -> None:
        posts: list[tuple[str, dict[str, object]]] = []

        class FakePlatformClient:
            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                posts.append((path, payload))
                return {
                    "schema": "tinyhat_private_credential_removal_v1",
                    "handoff_id": "sh_exa",
                    "credential_name": "EXA_API_KEY",
                    "status": "offered",
                }

        with mock.patch.object(
            credentials,
            "build_platform_client",
            return_value=(FakePlatformClient(), "local_dev"),
        ):
            payload = json.loads(
                credentials.credentials({"action": "remove", "handoff_id": "sh_exa"})
            )

        self.assertEqual(
            posts,
            [
                (
                    "/hapi/v1/computers/local-dev/private-credentials/v1/sh_exa/removal-requests",
                    {},
                )
            ],
        )
        self.assertEqual(payload["status"], "offered")
        self.assertIs(payload["chat_response_required"], False)

    def test_credentials_remove_resolves_one_case_insensitive_exact_name(self) -> None:
        gets: list[str] = []
        posts: list[tuple[str, dict[str, object]]] = []

        class FakePlatformClient:
            def get_json(self, path: str) -> dict[str, object]:
                gets.append(path)
                return {
                    "credentials": [
                        {"handoff_id": "sh_partial", "name": "EXA_API_KEY_BACKUP"},
                        {"handoff_id": "sh_exact", "name": "exa_api_key"},
                    ]
                }

            def post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
                posts.append((path, payload))
                return {"status": "offered"}

        client = FakePlatformClient()
        with mock.patch.object(
            credentials,
            "build_platform_client",
            return_value=(client, "local_dev"),
        ):
            payload = json.loads(
                credentials.credentials({"action": "remove", "name": "exa_api_key"})
            )

        self.assertEqual(
            gets,
            ["/hapi/v1/computers/local-dev/private-credentials/v1?q=EXA_API_KEY"],
        )
        self.assertEqual(
            posts,
            [
                (
                    "/hapi/v1/computers/local-dev/private-credentials/v1/sh_exact/removal-requests",
                    {},
                )
            ],
        )
        self.assertEqual(payload["status"], "offered")

    def test_credentials_remove_name_fallback_requires_one_exact_current_match(self) -> None:
        cases = {
            "partial matches only": {
                "name": "EXA",
                "credentials": [
                    {"handoff_id": "sh_primary", "name": "EXA_API_KEY"},
                    {"handoff_id": "sh_backup", "name": "EXA_BACKUP_KEY"},
                ],
            },
            "duplicate exact matches": {
                "name": "EXA_API_KEY",
                "credentials": [
                    {"handoff_id": "sh_first", "name": "EXA_API_KEY"},
                    {"handoff_id": "sh_second", "name": "exa_api_key"},
                ],
            },
            "exact match without selector": {
                "name": "EXA_API_KEY",
                "credentials": [{"handoff_id": "", "name": "EXA_API_KEY"}],
            },
        }

        for label, case in cases.items():
            with self.subTest(label=label):
                posts: list[tuple[str, dict[str, object]]] = []

                class FakePlatformClient:
                    def get_json(self, path: str) -> dict[str, object]:
                        return {"credentials": case["credentials"]}

                    def post_json(
                        self, path: str, payload: dict[str, object]
                    ) -> dict[str, object]:
                        posts.append((path, payload))
                        return {"status": "offered"}

                with mock.patch.object(
                    credentials,
                    "build_platform_client",
                    return_value=(FakePlatformClient(), "local_dev"),
                ):
                    payload = json.loads(
                        credentials.credentials(
                            {"action": "remove", "name": case["name"]}
                        )
                    )

                self.assertEqual(posts, [])
                self.assertEqual(payload["status"], "selection_required")
                self.assertEqual(payload["error"], "credential_not_unique")
                self.assertEqual(payload["credentials"], case["credentials"])

    def test_credentials_remove_without_selector_never_calls_platform(self) -> None:
        with mock.patch.object(credentials, "build_platform_client") as build_client:
            payload = json.loads(credentials.credentials({"action": "remove"}))

        build_client.assert_not_called()
        self.assertEqual(payload["status"], "selection_required")
        self.assertEqual(payload["error"], "missing_selector")

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
        self.assertIn("tinyhat_slack_connect", injected["context"])
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
                self.assertIn(
                    "call tinyhat_codex_auth once with action=prerequisite", injected["context"]
                )
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

    def test_context_hook_injects_for_plugin_update_requests(self) -> None:
        injected = tinyhat_context.inject_tinyhat_context(
            user_message="Plugin update check says target_ref_changed",
            is_first_turn=False,
        )

        self.assertIsNotNone(injected)
        assert injected is not None
        self.assertIn("tinyhat_plugin_update", injected["context"])
        self.assertIn("action=status", injected["context"])
        self.assertIn("restart_gateway=true", injected["context"])

    def test_context_hook_injects_for_skill_lookup_failures(self) -> None:
        injected = tinyhat_context.inject_tinyhat_context(
            user_message='skill_view(name="tinyhat-codex-auth") failed',
            is_first_turn=False,
        )

        self.assertIsNotNone(injected)
        assert injected is not None
        self.assertIn("tinyhat_skill_catalog", injected["context"])
        self.assertIn("tinyhat:tinyhat-codex-auth", injected["context"])

    def test_context_hook_injects_for_tinyhat_qa_reports(self) -> None:
        injected = tinyhat_context.inject_tinyhat_context(
            user_message="Post this Slack report about a gateway restart bug",
            is_first_turn=False,
        )

        self.assertIsNotNone(injected)
        assert injected is not None
        self.assertIn("do not use terminal/curl just to post the text", injected["context"])

    def test_context_hook_injects_for_privacy_questions(self) -> None:
        examples = (
            "Can the operators read my messages?",
            "Who can see my chat history with you?",
            "Do you keep logs of this conversation anywhere?",
            "Is this chat monitored by tinyhat staff?",
            "How is my data protected here?",
            "Where is this conversation stored?",
            "Can support staff view this chat?",
            "Is anyone reading this conversation?",
            "Are you recording our chat?",
            "Can employees inspect my files?",
            "آیا ادمین‌ها به پیام‌های من دسترسی دارن؟",
            "آیا ادمین ها به پیامهای من دسترسی دارن؟",
            "آيا كسی به پیامهای من دسترسی داره؟",
            "حریم خصوصی من اینجا چطور حفظ میشه؟",
            "کسی مکالمه‌های منو می‌خونه؟",
            "حریم خصوصی؟",
            "درباره حریم خصوصی، توضیح بده",
            "پیام‌هامو می‌خونید؟",
            "آیا مکالمه‌های من ضبط می‌شوند؟",
            "آیا کسی پیام‌های من را می‌خواند؟",
            "آیا شما پیام‌های من را می‌خوانید؟",
        )
        for user_message in examples:
            with self.subTest(user_message=user_message):
                injected = tinyhat_context.inject_tinyhat_context(
                    user_message=user_message,
                    is_first_turn=False,
                )
                self.assertIsNotNone(injected)
                assert injected is not None
                self.assertIn("tinyhat:tinyhat-privacy", injected["context"])
                self.assertIn("dedicated Computer", injected["context"])
                self.assertIn("routine operations", injected["context"])
                self.assertIn("affirmatively requests or permits", injected["context"])
                self.assertIn("https://tinyhat.ai/privacy", injected["context"])
                self.assertIn("private Computers", injected["context"])

    def test_context_hook_injects_for_funding_questions(self) -> None:
        examples = (
            "How am I paying for this?",
            "What happens when my credits run out?",
            "Is this bot free to use?",
            "Who is funding this agent?",
            "What does it cost to keep you running?",
            "What is my balance?",
            "How does billing work?",
            "What is the price?",
            "What payment methods do you accept?",
            "How much does it cost?",
            "How much does this cost?",
            "Is it free?",
            "How is this funded?",
            "What are my payment options?",
            "How much credit is left?",
            "Can you tell me what this costs?",
            "Could you explain how much you cost?",
            "What are your prices?",
            "What are your rates?",
            "What are your fees?",
            "Can you tell me your prices?",
            "Could you explain your rates?",
            "Would you show me your fees?",
            "Check my balance?",
        )
        for user_message in examples:
            with self.subTest(user_message=user_message):
                injected = tinyhat_context.inject_tinyhat_context(
                    user_message=user_message,
                    is_first_turn=False,
                )
                self.assertIsNotNone(injected)
                assert injected is not None
                self.assertIn("starter credit", injected["context"])
                self.assertIn("about $10", injected["context"])
                self.assertIn("/codex_auth", injected["context"])
                self.assertIn("tinyhat:tinyhat-codex-auth", injected["context"])

    def test_context_states_funding_reminder_rules(self) -> None:
        directive = tinyhat_context.FUNDING_REMINDER_DIRECTIVE
        self.assertTrue(directive.startswith("[System note:"))
        self.assertTrue(directive.endswith("]"))
        self.assertIn(
            "One-time funding note for this Computer",
            directive,
        )
        self.assertNotIn(
            "first conversation on this",
            directive,
        )
        self.assertIn(
            "make it one of the onboarding steps",
            directive,
        )
        self.assertIn(
            "numbered or bulleted step when the reply lists",
            directive,
        )
        self.assertIn(
            "one standalone step line",
            directive,
        )
        self.assertIn(
            "same reply as any introduction or profile-build offer",
            directive,
        )
        self.assertIn(
            "Never demote it to a footnote,",
            directive,
        )
        self.assertIn(
            "Connect your ChatGPT/Codex subscription with /codex_auth",
            directive,
        )
        self.assertIn("skip this note silently", directive)
        self.assertIn("action=status", directive)
        self.assertIn("tool-owned native response", directive)
        self.assertIn("Never repeat this note", directive)
        self.assertIn("never block the user's actual request", directive)
        self.assertIn(
            "Never state a remaining credit balance",
            tinyhat_context.TINYHAT_CONTEXT,
        )
        self.assertIn(
            "check tinyhat_codex_auth with action=status",
            tinyhat_context.TINYHAT_CONTEXT,
        )

    def test_context_stays_under_hermes_hook_spill_cap(self) -> None:
        # Hermes spills pre_llm_call context above ~10,000 chars to a disk
        # file and injects only a 500-char head/tail preview. A context blob
        # over the cap silently stops reaching the model inline on every
        # injected turn. If this fails, slim TINYHAT_CONTEXT — do not raise
        # the number.
        self.assertLess(len(tinyhat_context.TINYHAT_CONTEXT), 10_000)

    def test_onboarding_turn_payload_fits_under_spill_cap(self) -> None:
        first = tinyhat_context.inject_tinyhat_context(
            user_message="hello",
            is_first_turn=True,
        )
        assert first is not None
        self.assertLessEqual(
            len(first["context"]), tinyhat_context._HOOK_SPILL_SAFE_CHARS
        )
        # Literal ceiling: Hermes spills at ~10,000 chars regardless of our
        # tunable safe margin, so producer and test cannot drift together.
        self.assertLess(len(first["context"]), 10_000)
        self.assertTrue(first["context"].startswith("[System note:"))
        self.assertIn("Tinyhat context:", first["context"])

    def test_compose_onboarding_context_trims_at_bullet_boundary(self) -> None:
        small = "Tinyhat context: heading.\n- first bullet.\n- second bullet."
        untouched = tinyhat_context._compose_onboarding_context(small, "hi")
        self.assertEqual(
            untouched,
            tinyhat_context.FUNDING_REMINDER_DIRECTIVE + "\n" + small,
        )

        bullets = "".join(
            f"\n- bullet {i} " + "x" * 400 for i in range(40)
        )
        oversized = "Tinyhat context: heading." + bullets
        composed = tinyhat_context._compose_onboarding_context(oversized, "hi")
        self.assertLessEqual(
            len(composed), tinyhat_context._HOOK_SPILL_SAFE_CHARS
        )
        self.assertLess(len(composed), 10_000)
        self.assertTrue(
            composed.startswith(
                tinyhat_context.FUNDING_REMINDER_DIRECTIVE
                + "\nTinyhat context: heading."
            )
        )
        # Whole bullets only, never a mid-bullet cut: every kept bullet is
        # complete (full 400-character payload) — and at least one bullet
        # must survive so this loop cannot pass vacuously.
        kept_bullets = composed.split("\n- ")[1:]
        self.assertGreaterEqual(len(kept_bullets), 1)
        for kept in kept_bullets:
            self.assertTrue(kept.startswith("bullet"))
            self.assertTrue(kept.rstrip().endswith("x" * 400))

    def test_compose_onboarding_context_protects_matched_bullets(self) -> None:
        filler = "".join(f"\n- filler {i} " + "x" * 400 for i in range(40))
        privacy_bullet = (
            "\n"
            + tinyhat_context._PRIVACY_BULLET_MARKER
            + " trust model facts "
            + "y" * 400
        )
        oversized = "Tinyhat context: heading." + filler + privacy_bullet
        # A neutral first message drops the tail privacy bullet.
        neutral = tinyhat_context._compose_onboarding_context(oversized, "hi")
        self.assertNotIn(tinyhat_context._PRIVACY_BULLET_MARKER, neutral)
        # A privacy question keeps it despite its tail position.
        asking = tinyhat_context._compose_onboarding_context(
            oversized, "Can the operators read my messages?"
        )
        self.assertIn(tinyhat_context._PRIVACY_BULLET_MARKER, asking)
        self.assertLessEqual(len(asking), tinyhat_context._HOOK_SPILL_SAFE_CHARS)
        self.assertLess(len(asking), 10_000)

    def test_onboarding_turn_preserves_privacy_context_for_privacy_question(
        self,
    ) -> None:
        first = tinyhat_context.inject_tinyhat_context(
            user_message="Can the operators read my messages?",
            is_first_turn=True,
        )
        assert first is not None
        self.assertLessEqual(
            len(first["context"]), tinyhat_context._HOOK_SPILL_SAFE_CHARS
        )
        self.assertLess(len(first["context"]), 10_000)
        self.assertTrue(first["context"].startswith("[System note:"))
        self.assertIn("tinyhat:tinyhat-privacy", first["context"])
        self.assertIn("https://tinyhat.ai/privacy", first["context"])
        self.assertIn("routine operations", first["context"])

    def test_onboarding_turn_preserves_privacy_context_for_routed_wording(
        self,
    ) -> None:
        # Routed by the generic term table ("privacy"), not the strict
        # privacy-intent matcher: protection must derive from the same
        # signals that route the request.
        first = tinyhat_context.inject_tinyhat_context(
            user_message="Could you explain the privacy policy?",
            is_first_turn=True,
        )
        assert first is not None
        self.assertLess(len(first["context"]), 10_000)
        self.assertIn("tinyhat:tinyhat-privacy", first["context"])
        self.assertIn("https://tinyhat.ai/privacy", first["context"])

    def test_onboarding_turn_preserves_qa_report_guard(self) -> None:
        # An existing routed contract must not regress on the one turn
        # that carries the funding note: the QA/reporting guard bullet
        # survives its own first-turn request — including alias phrases
        # ("qa report", "bug report") whose text does not appear in the
        # bullet literally.
        for user_message in (
            "Post this Slack report about a gateway restart bug",
            "Please post this QA report about a restart bug",
            "Please post this QA report about a reload bug",
        ):
            with self.subTest(user_message=user_message):
                first = tinyhat_context.inject_tinyhat_context(
                    user_message=user_message,
                    is_first_turn=True,
                )
                assert first is not None
                self.assertLess(len(first["context"]), 10_000)
                self.assertIn("do not use terminal/curl", first["context"])
                self._reset_funding_marker()

    def test_onboarding_turn_prioritizes_intent_bullet_over_terms(self) -> None:
        # "tinyhat" is a generic routing term matching many early
        # bullets; the explicit privacy intent must still reserve the
        # trust-model bullet first.
        first = tinyhat_context.inject_tinyhat_context(
            user_message="Is this chat monitored by tinyhat staff?",
            is_first_turn=True,
        )
        assert first is not None
        self.assertLess(len(first["context"]), 10_000)
        self.assertIn("tinyhat:tinyhat-privacy", first["context"])
        self.assertIn("routine operations", first["context"])
        self.assertIn("https://tinyhat.ai/privacy", first["context"])

    def test_onboarding_turn_reserves_owner_bullet_over_terms(self) -> None:
        # The alias-owned bullet must outrank broad literal term matches:
        # adding the generic "tinyhat" term to a QA-report request must
        # not crowd out the QA guard bullet the phrase routes to.
        first = tinyhat_context.inject_tinyhat_context(
            user_message="Please post this Tinyhat QA report about a reload bug",
            is_first_turn=True,
        )
        assert first is not None
        self.assertLess(len(first["context"]), 10_000)
        self.assertIn("do not use terminal/curl", first["context"])

    def test_onboarding_turn_keeps_privacy_bullet_for_modal_wordings(
        self,
    ) -> None:
        # "privacy" is owner-ranked, and a modal inquiry wrapper ("can
        # you tell me ...") is a question about access, not a work
        # request — both first-turn phrasings must keep the trust-model
        # bullet.
        for user_message in (
            "Could you explain Tinyhat's privacy policy?",
            "Can you tell me who can read my messages?",
        ):
            with self.subTest(user_message=user_message):
                first = tinyhat_context.inject_tinyhat_context(
                    user_message=user_message,
                    is_first_turn=True,
                )
                assert first is not None
                self.assertLess(len(first["context"]), 10_000)
                self.assertIn("tinyhat:tinyhat-privacy", first["context"])
                self.assertIn("https://tinyhat.ai/privacy", first["context"])
                self._reset_funding_marker()

    def test_onboarding_turn_maps_privacy_terms_to_privacy_bullet(self) -> None:
        # gdpr / surveillance route through the generic term table but
        # appear nowhere in the privacy bullet text; the term hints must
        # carry them to it.
        for user_message in ("GDPR?", "Is this surveillance?"):
            with self.subTest(user_message=user_message):
                first = tinyhat_context.inject_tinyhat_context(
                    user_message=user_message,
                    is_first_turn=True,
                )
                assert first is not None
                self.assertLess(len(first["context"]), 10_000)
                self.assertIn("tinyhat:tinyhat-privacy", first["context"])
                self._reset_funding_marker()

    def test_onboarding_turn_preserves_underscore_phrase_guards(self) -> None:
        # Raw-form phrases ("skills_list") must count as route signals
        # exactly as the router counts them.
        first = tinyhat_context.inject_tinyhat_context(
            user_message="skills_list does not show the privacy skill",
            is_first_turn=True,
        )
        assert first is not None
        self.assertLess(len(first["context"]), 10_000)
        self.assertIn("tinyhat_skill_catalog", first["context"])
        self.assertIn("tinyhat:tinyhat-privacy", first["context"])

    def test_compose_onboarding_context_degenerate_inputs_stay_capped(
        self,
    ) -> None:
        with mock.patch.object(
            tinyhat_context, "FUNDING_REMINDER_DIRECTIVE", "X" * 12_000
        ):
            capped = tinyhat_context._compose_onboarding_context(
                "Tinyhat context: heading.\n- a bullet.", "hi"
            )
            self.assertLessEqual(
                len(capped), tinyhat_context._HOOK_SPILL_SAFE_CHARS
            )
        heading_only = tinyhat_context._compose_onboarding_context(
            "H" * 12_000, "hi"
        )
        self.assertLessEqual(
            len(heading_only), tinyhat_context._HOOK_SPILL_SAFE_CHARS
        )
        self.assertLess(len(heading_only), 10_000)
        # The oversized-heading branch with bullets present must also
        # stay hard-capped (a different code path than no-bullet input).
        heading_with_bullet = tinyhat_context._compose_onboarding_context(
            "H" * 12_000 + "\n- tail bullet after a giant heading.", "hi"
        )
        self.assertLessEqual(
            len(heading_with_bullet), tinyhat_context._HOOK_SPILL_SAFE_CHARS
        )
        self.assertLess(len(heading_with_bullet), 10_000)

    def test_onboarding_turn_preserves_funding_context_for_funding_question(
        self,
    ) -> None:
        first = tinyhat_context.inject_tinyhat_context(
            user_message="How am I paying for you?",
            is_first_turn=True,
        )
        assert first is not None
        self.assertLessEqual(
            len(first["context"]), tinyhat_context._HOOK_SPILL_SAFE_CHARS
        )
        self.assertLess(len(first["context"]), 10_000)
        self.assertIn("- Funding model:", first["context"])
        self.assertIn("Never state a remaining credit balance", first["context"])

    def test_funding_reminder_directive_is_once_per_computer(self) -> None:
        first = tinyhat_context.inject_tinyhat_context(
            user_message="hello",
            is_first_turn=True,
        )
        assert first is not None
        self.assertIn(tinyhat_context.FUNDING_REMINDER_DIRECTIVE, first["context"])
        marker = Path(self._hermes_home.name) / "tinyhat-funding-reminder-shown"
        self.assertTrue(marker.is_file())

        reset_session = tinyhat_context.inject_tinyhat_context(
            user_message="hello again after /new",
            is_first_turn=True,
        )
        assert reset_session is not None
        self.assertNotIn(
            tinyhat_context.FUNDING_REMINDER_DIRECTIVE,
            reset_session["context"],
        )

        later_turn = tinyhat_context.inject_tinyhat_context(
            user_message="tinyhat status",
            is_first_turn=False,
        )
        assert later_turn is not None
        self.assertNotIn(
            tinyhat_context.FUNDING_REMINDER_DIRECTIVE,
            later_turn["context"],
        )

    def test_context_hook_skips_generic_funding_terms(self) -> None:
        examples = (
            "Please free this buffer",
            "Balance your binary tree",
            "Price your API response",
            "Fund your test fixture",
            "Could you check my balance factor in this AVL tree?",
            "Can you show who pays for each invoice in this CSV?",
            "Could you look for free to use in the README?",
            "Could you list projects funded by NASA?",
            "Check my balance factor in this AVL tree?",
            "Show who pays for each invoice in this CSV?",
            "Look for free to use in the README?",
            "List projects funded by NASA?",
            "Can you rename how_much_do_you_cost?",
            "Could you add a test named is_it_free?",
            'Could you search for "how much do you cost" in README.md?',
            "Rename your_prices to price_list",
            "Sort your_rates before rendering",
            "Serialize your_fees as JSON",
            "Estimate the cost of this query",
            "Balance this binary tree",
            "Change the price field",
            "Fund the test fixture",
            "Can you free this buffer?",
            "Could you balance this binary tree?",
            "Estimate the cost of running this query",
            "Who pays attention to this warning?",
            "Is this free variable captured?",
            "The balance factor of this AVL tree is wrong",
            "How do I pay attention to failing tests?",
            "What does it cost to sort this list?",
            "Check the balance factor in this AVL tree",
            "Look for free variables in this closure",
            "Check my balance factor in this AVL tree",
            "Look for free to use in the README",
            "Show who pays for each invoice in this CSV",
        )
        for user_message in examples:
            with self.subTest(user_message=user_message):
                self.assertIsNone(
                    tinyhat_context.inject_tinyhat_context(
                        user_message=user_message,
                        is_first_turn=False,
                    )
                )

    def test_codex_auth_skill_states_funding_model(self) -> None:
        skill_md = REPO_ROOT / "skills" / "tinyhat-codex-auth" / "SKILL.md"
        text = " ".join(skill_md.read_text(encoding="utf-8").split())

        self.assertIn("small starter credit (about $10)", text)
        self.assertIn("intended ongoing fund", text)
        self.assertIn("one-time funding note exactly once per Computer", text)
        self.assertIn("as **one of the onboarding steps**", text)
        self.assertIn("Never demote it to a footnote", text)
        self.assertIn("skip it silently when a subscription is already connected", text)
        self.assertIn("Present it once — not in every reply", text)
        self.assertIn("durable per-Computer marker", text)
        self.assertIn("tool-owned native response", text)
        self.assertIn("Never block or delay the user's actual request", text)
        self.assertIn("Never state a remaining credit balance", text)
        self.assertIn('{"action": "status"}', text)
        self.assertIn("/codex_auth", text)

    def test_funding_reminder_claim_fails_closed_without_hermes_home(self) -> None:
        os.environ["TINYHAT_HERMES_HOME"] = str(
            Path(self._hermes_home.name) / "does-not-exist"
        )
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                injected = tinyhat_context.inject_tinyhat_context(
                    user_message="hello",
                    is_first_turn=True,
                )
                assert injected is not None
                self.assertNotIn(
                    tinyhat_context.FUNDING_REMINDER_DIRECTIVE,
                    injected["context"],
                )

    def test_funding_reminder_claim_is_exclusive(self) -> None:
        self.assertTrue(tinyhat_context._claim_funding_reminder())
        self.assertFalse(tinyhat_context._claim_funding_reminder())

    def test_context_hook_skips_generic_developer_terms(self) -> None:
        examples = (
            "Make this GitHub repository private",
            "Please log the HTTP response",
            "Review the security headers",
            "I trust this certificate",
            "Tail the application logs",
            "Explain operator precedence",
            "Please migrate my database",
            "برای سایت یه بلاگ بنویس",
            "Read the application logs",
            "Look at this file",
            "Store this file under /tmp",
            "فایل رو ذخیره کن",
            "فایل رو بخون",
            "فایل رو ببین",
            "Can you read this file?",
            "Could you look at my logs?",
            "پیام من را بخوان",
            "Please look at my logs",
            "Please read my messages",
        )
        for user_message in examples:
            with self.subTest(user_message=user_message):
                self.assertIsNone(
                    tinyhat_context.inject_tinyhat_context(
                        user_message=user_message,
                        is_first_turn=False,
                    )
                )

    def test_privacy_access_wording_is_policy_exact_everywhere(self) -> None:
        fragments = (
            "affirmatively requests or permits",
            "protect the service, or maintain security",
            "required by law",
        )
        files = (
            REPO_ROOT / "skills" / "tinyhat-privacy" / "SKILL.md",
            REPO_ROOT / "skills" / "tinyhat-platform" / "SKILL.md",
            REPO_ROOT / "README.md",
            REPO_ROOT / "docs" / "capabilities.md",
            REPO_ROOT / "CHANGELOG.md",
        )
        for path in files:
            text = " ".join(path.read_text(encoding="utf-8").split())
            for fragment in fragments:
                with self.subTest(path=path.name, fragment=fragment):
                    self.assertIn(fragment, text)
        for fragment in fragments:
            with self.subTest(path="context.py", fragment=fragment):
                self.assertIn(fragment, tinyhat_context.TINYHAT_CONTEXT)
        skill_text = (REPO_ROOT / "skills" / "tinyhat-privacy" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        facts_and_example = skill_text.split("## Do Not")[0].lower()
        for banned in ("like any hosted service", "like every hosted service"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, facts_and_example)
                self.assertNotIn(banned, tinyhat_context.TINYHAT_CONTEXT.lower())

    def test_privacy_skill_states_the_trust_model(self) -> None:
        skill_md = REPO_ROOT / "skills" / "tinyhat-privacy" / "SKILL.md"
        text = " ".join(skill_md.read_text(encoding="utf-8").split())

        self.assertIn("dedicated Computer created for this user alone", text)
        self.assertIn(
            "Tinyhat does not read the contents of a customer's Computer",
            text,
        )
        self.assertIn("routine operations", text)
        self.assertIn("affirmatively requests or permits", text)
        self.assertIn("protect the service, or maintain security", text)
        self.assertIn("required by law", text)
        self.assertIn(
            "violate Tinyhat's own Terms of Service and Privacy Policy",
            text,
        )
        self.assertIn("https://tinyhat.ai/privacy", text)
        self.assertIn("https://tinyhat.ai/terms", text)
        self.assertIn("privacy@tinyloop.co", text)
        self.assertIn("private Computers", text)
        self.assertIn("Do not claim access is technically impossible today", text)
        self.assertIn("Do not name individual operators", text)
        self.assertIn("Answer in the user's language", text)

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
            tools._start_runtime_codex_auth = lambda: (
                start_calls.append(True)
                or {
                    "ok": True,
                }
            )

            payload = json.loads(tools.codex_auth({"action": "prerequisite"}))
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

    def test_codex_auth_missing_action_error_is_actionable(self) -> None:
        payload = json.loads(tools.codex_auth({}))

        self.assertEqual(payload["schema"], "tinyhat_tool_error_v1")
        self.assertEqual(payload["tool"], "tinyhat_codex_auth")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "missing_required_parameter")
        self.assertEqual(payload["missing"], ["action"])
        self.assertEqual(payload["example_call"], {"action": "prerequisite"})

    def test_codex_auth_rejects_unknown_action_with_enum(self) -> None:
        payload = json.loads(tools.codex_auth({"action": "launch"}))

        self.assertEqual(payload["schema"], "tinyhat_tool_error_v1")
        self.assertEqual(payload["error"], "invalid_parameter")
        self.assertEqual(
            payload["expected"]["action"],
            ["prerequisite", "start", "status", "log", "limits"],
        )

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
            tools._start_runtime_codex_auth = lambda: (
                start_calls.append(True)
                or {
                    "ok": True,
                }
            )

            payload = json.loads(tools.codex_auth({"action": "start"}))
        finally:
            tools._start_runtime_codex_auth = original_start

        self.assertEqual(payload["schema"], "tinyhat_tool_error_v1")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "confirmation_required")
        self.assertIn("Enable device code authorization", payload["message"])
        self.assertIn("/codex_auth", payload["message"])
        self.assertEqual(
            payload["example_call"],
            {"action": "start", "confirmed": True},
        )
        self.assertEqual(start_calls, [])

    def test_codex_auth_tool_starts_after_confirmation(self) -> None:
        original_prerequisite = tools._send_codex_prerequisite
        original_start = tools._start_runtime_codex_auth
        prerequisite_calls = []
        try:
            tools._send_codex_prerequisite = lambda: (
                prerequisite_calls.append(True)
                or {
                    "ok": True,
                    "mode": "photo",
                }
            )
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

    def test_codex_auth_runtime_inspection_actions(self) -> None:
        original_run = tools._run_runtime_command
        calls: list[str] = []
        try:
            tools._run_runtime_command = lambda script, **_: (
                calls.append(script)
                or {
                    "ok": True,
                    "returncode": 0,
                    "stdout": "runtime output",
                    "stderr": "",
                }
            )

            status_payload = json.loads(tools.codex_auth({"action": "status"}))
            log_payload = json.loads(tools.codex_auth({"action": "log"}))
            limits_payload = json.loads(tools.codex_auth({"action": "limits"}))
        finally:
            tools._run_runtime_command = original_run

        self.assertEqual(status_payload["schema"], "tinyhat_codex_auth_action_v1")
        self.assertEqual(status_payload["action"], "status")
        self.assertEqual(status_payload["status"], "ok")
        self.assertEqual(log_payload["action"], "log")
        self.assertEqual(limits_payload["action"], "limits")
        self.assertIn("telegram_codex_auth status", calls[0])
        self.assertIn("telegram_codex_auth log", calls[1])
        self.assertIn("codex_limits telegram", calls[2])

    def test_plugin_update_missing_action_error_is_actionable(self) -> None:
        payload = json.loads(tools.plugin_update({}))

        self.assertEqual(payload["schema"], "tinyhat_tool_error_v1")
        self.assertEqual(payload["tool"], "tinyhat_plugin_update")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "missing_required_parameter")
        self.assertEqual(payload["missing"], ["action"])
        self.assertEqual(payload["example_call"], {"action": "status"})

    def test_plugin_update_status_uses_runtime_status_command(self) -> None:
        original_run = tools._run_runtime_json_command
        calls: list[str] = []
        try:
            tools._run_runtime_json_command = lambda kind, **_: (
                calls.append(kind)
                or {
                    "ok": True,
                    "command": kind,
                    "result": {"update_available": True, "decision": "target_ref_changed"},
                    "process": {"ok": True},
                    "parse_error": None,
                }
            )

            payload = json.loads(tools.plugin_update({"action": "status"}))
        finally:
            tools._run_runtime_json_command = original_run

        self.assertEqual(calls, ["tinyhat_plugin_status"])
        self.assertEqual(payload["schema"], "tinyhat_plugin_update_action_v1")
        self.assertEqual(payload["action"], "status")
        self.assertEqual(payload["status"], "ok")
        self.assertIn("update_available", payload["result"]["result"])
        self.assertIn("action=update", payload["next_action"])

    def test_plugin_update_requires_confirmation_before_apply(self) -> None:
        original_run = tools._run_runtime_json_command
        calls: list[str] = []
        try:
            tools._run_runtime_json_command = lambda kind, **_: (
                calls.append(kind)
                or {
                    "ok": True,
                    "command": kind,
                    "result": {},
                    "process": {"ok": True},
                    "parse_error": None,
                }
            )

            payload = json.loads(tools.plugin_update({"action": "update"}))
        finally:
            tools._run_runtime_json_command = original_run

        self.assertEqual(payload["schema"], "tinyhat_tool_error_v1")
        self.assertEqual(payload["error"], "confirmation_required")
        self.assertEqual(calls, [])

    def test_plugin_update_can_apply_and_restart_gateway(self) -> None:
        original_run = tools._run_runtime_json_command
        calls: list[str] = []
        try:
            tools._run_runtime_json_command = lambda kind, **_: (
                calls.append(kind)
                or {
                    "ok": True,
                    "command": kind,
                    "result": {"kind": kind, "healthy": True},
                    "process": {"ok": True},
                    "parse_error": None,
                }
            )

            payload = json.loads(
                tools.plugin_update(
                    {
                        "action": "update",
                        "confirmed": True,
                        "restart_gateway": True,
                    }
                )
            )
        finally:
            tools._run_runtime_json_command = original_run

        self.assertEqual(calls, ["update_tinyhat_plugin", "stop_hermes", "start_hermes"])
        self.assertEqual(payload["schema"], "tinyhat_plugin_update_action_v1")
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["restart_gateway"]["requested"])

    def test_plugin_update_fails_if_gateway_stop_fails(self) -> None:
        original_run = tools._run_runtime_json_command
        results = {
            "update_tinyhat_plugin": {"ok": True},
            "stop_hermes": {"ok": False},
            "start_hermes": {"ok": True},
        }
        try:
            tools._run_runtime_json_command = lambda kind, **_: {
                "ok": results[kind]["ok"],
                "command": kind,
                "result": {},
                "process": {"ok": results[kind]["ok"]},
                "parse_error": None,
            }

            payload = json.loads(
                tools.plugin_update(
                    {
                        "action": "update",
                        "confirmed": True,
                        "restart_gateway": True,
                    }
                )
            )
        finally:
            tools._run_runtime_json_command = original_run

        self.assertEqual(payload["status"], "failed")

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

    def test_slack_connect_sends_hermes_agent_manifest_and_starts_worker(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.path = ""
                self.payload: dict = {}

            def post_json(self, path: str, payload: dict) -> dict:
                self.path = path
                self.payload = payload
                return {
                    "handoff_id": "sh_slack",
                    "status": "pending",
                    "secret_name": "SLACK_CONNECTION",
                    "handoff_kind": "slack_connection",
                }

        fake_client = FakeClient()
        manifest = {
            "features": {"agent_view": {"agent_description": "Hermes"}},
            "settings": {"socket_mode_enabled": True},
        }
        worker_calls: list[tuple[dict, str]] = []
        with (
            mock.patch.object(
                slack_connection,
                "_generate_hermes_slack_manifest",
                return_value=manifest,
            ),
            mock.patch.object(
                slack_connection,
                "_generate_key_pair",
                return_value=("PRIVATE", "PUBLIC"),
            ),
            mock.patch.object(
                slack_connection,
                "build_platform_client",
                return_value=(fake_client, "local_dev"),
            ),
            mock.patch.object(
                slack_connection,
                "_start_worker_process",
                side_effect=lambda handoff, key: worker_calls.append((handoff, key)),
            ),
        ):
            reply = tools.slack_connect({})

        self.assertEqual(
            fake_client.path,
            "/hapi/v1/computers/local-dev/private-secret-handoffs/v1",
        )
        self.assertEqual(fake_client.payload["handoff_kind"], "slack_connection")
        self.assertEqual(fake_client.payload["expires_in_seconds"], 30 * 60)
        self.assertIs(fake_client.payload["slack_manifest"], manifest)
        self.assertEqual(worker_calls[0][1], "PRIVATE")
        self.assertIn("Hermes Agent-view manifest", reply)
        self.assertIn("never sees the tokens or Slack messages", reply)

    def test_slack_disconnect_starts_platform_owned_confirmation(self) -> None:
        calls: list[tuple[str, dict]] = []
        worker_calls: list[dict] = []

        class FakeClient:
            def post_json(self, path: str, payload: dict) -> dict:
                calls.append((path, payload))
                return {
                    "schema": "tinyhat_private_credential_removal_v1",
                    "removal_id": "scr_slack",
                    "handoff_id": "sh_slack",
                    "credential_name": "SLACK_CONNECTION",
                    "status": "offered",
                    "expires_at": "2026-07-31T20:00:00Z",
                    "telegram_message_sent": True,
                    "detail": "Review the Telegram confirmation.",
                }

        with (
            mock.patch.object(
                slack_connection,
                "build_platform_client",
                return_value=(FakeClient(), "local_dev"),
            ),
            mock.patch.object(
                slack_connection,
                "start_slack_disconnect_worker",
                side_effect=worker_calls.append,
            ),
        ):
            payload = json.loads(tools.slack_disconnect({}))

        self.assertEqual(
            calls,
            [("/hapi/v1/computers/local-dev/slack/disconnect/v1", {})],
        )
        self.assertEqual(payload["status"], "offered")
        self.assertTrue(payload["telegram_message_sent"])
        self.assertFalse(payload["chat_response_required"])
        self.assertIn("two-stage Slack disconnect", payload["agent_instruction"])
        self.assertEqual(worker_calls[0]["removal_id"], "scr_slack")

    def test_slack_disconnect_revokes_then_removes_complete_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "SLACK_BOT_TOKEN=bot-under-test\n"
                "SLACK_APP_TOKEN=app-under-test\n"
                "SLACK_ALLOWED_USERS=U012ABCDEF\n"
                "SLACK_HOME_CHANNEL=D012ABCDEF\n"
                "SLACK_HOME_CHANNEL_NAME='Owner DM'\n"
                "_HERMES_FORCE_SLACK_BOT_TOKEN=bot-under-test\n"
                "KEEP_ME=yes\n",
                encoding="utf-8",
            )
            synced: list[tuple[list[str], list[str]]] = []

            def read_values(paths, *, names):
                values: dict[str, str] = {}
                for path in paths:
                    for line in path.read_text(encoding="utf-8").splitlines():
                        if "=" not in line:
                            continue
                        key, value = line.split("=", 1)
                        if key in names:
                            values[key] = value
                return values

            def sync(names, *, remove_names):
                synced.append((list(names), list(remove_names)))
                return {"removed_names": list(remove_names)}

            with (
                mock.patch.object(
                    slack_disconnect,
                    "_runtime_helpers",
                    return_value=(
                        lambda: [env_path],
                        read_values,
                        sync,
                        lambda name: f"_HERMES_FORCE_{name}",
                    ),
                ),
                mock.patch.object(
                    slack_disconnect,
                    "_revoke_slack_bot_access",
                    return_value={"status": "revoked", "confirmed": True},
                ),
            ):
                result = slack_disconnect.disconnect_slack_locally()

            self.assertTrue(result["local_bundle_absent"])
            self.assertEqual(result["slack_access"]["status"], "revoked")
            self.assertEqual(env_path.read_text(encoding="utf-8"), "KEEP_ME=yes\n")
            self.assertEqual(synced[0][1], list(slack_disconnect.SLACK_ENV_NAMES))
            self.assertNotIn("bot-under-test", json.dumps(result))
            self.assertNotIn("app-under-test", json.dumps(result))

    def test_slack_disconnect_keeps_bundle_when_revoke_is_unconfirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            original = "SLACK_BOT_TOKEN=bot-under-test\nKEEP_ME=yes\n"
            env_path.write_text(original, encoding="utf-8")

            with (
                mock.patch.object(
                    slack_disconnect,
                    "_runtime_helpers",
                    return_value=(
                        lambda: [env_path],
                        lambda _paths, *, names: {"SLACK_BOT_TOKEN": "bot-under-test"},
                        mock.Mock(),
                        lambda name: f"_HERMES_FORCE_{name}",
                    ),
                ),
                mock.patch.object(
                    slack_disconnect,
                    "_revoke_slack_bot_access",
                    return_value={"status": "unconfirmed", "confirmed": False},
                ),
            ):
                result = slack_disconnect.disconnect_slack_locally()

            self.assertFalse(result["local_bundle_absent"])
            self.assertEqual(result["failure_code"], "slack_revoke_unconfirmed")
            self.assertEqual(env_path.read_text(encoding="utf-8"), original)

    def test_slack_disconnect_worker_waits_for_owner_confirmation(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.states = iter(
                    [
                        {"status": "offered", "poll_after_ms": 1},
                        {"status": "confirmed", "poll_after_ms": 1},
                    ]
                )
                self.posts: list[tuple[str, dict]] = []
                self.post_attempts = 0

            def get_json(self, _path: str) -> dict:
                return next(self.states)

            def post_json(self, path: str, payload: dict) -> dict:
                self.post_attempts += 1
                self.posts.append((path, payload))
                if self.post_attempts == 1:
                    raise platform.PlatformError("temporary outage")
                return {"status": "queued"}

        fake_client = FakeClient()
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                slack_disconnect_worker,
                "STATE_DIR",
                Path(tmp),
            ),
            mock.patch.object(
                slack_disconnect_worker,
                "build_platform_client",
                return_value=(fake_client, "local_dev"),
            ),
            mock.patch.object(
                slack_disconnect_worker,
                "disconnect_slack_locally",
                return_value={
                    "schema": "tinyhat_plugin_slack_disconnect_v1",
                    "local_bundle_absent": True,
                    "slack_access": {"status": "revoked", "confirmed": True},
                },
            ),
            mock.patch.object(slack_disconnect_worker.time, "sleep"),
        ):
            slack_disconnect_worker.run_worker(
                handoff_id="sh_slack",
                removal_id="scr_abcdefghijklmnopqrstuvwx",
                expires_at="2099-07-31T20:00:00Z",
            )

        self.assertEqual(len(fake_client.posts), 2)
        path, payload = fake_client.posts[-1]
        self.assertEqual(
            path,
            "/hapi/v1/computers/local-dev/slack/disconnect/v1/sh_slack/result",
        )
        self.assertEqual(payload["removal_id"], "scr_abcdefghijklmnopqrstuvwx")
        self.assertTrue(payload["local_bundle_absent"])

    def test_slack_bundle_installs_connection_and_private_home_channel(self) -> None:
        bot_token = "xoxb-" + "placeholder"
        app_token = "xapp-" + "placeholder"
        plaintext = json.dumps(
            {
                "schema": "tinyhat_slack_connection_bundle_v1",
                "bot_token": bot_token,
                "app_token": app_token,
                "allowed_users": "U012ABCDEF",
            }
        )
        saved: list[tuple[str, str]] = []
        claims: list[dict] = []
        slack_calls: list[tuple[str, dict]] = []
        notices: list[str] = []
        metadata = {
            "provider": "slack",
            "app_id": "A012ABCDEF",
            "app_name": "Forecast Agent",
            "workspace_id": "T012ABCDEF",
            "workspace_name": "Tinyloop",
            "allowed_user_count": 1,
        }
        with (
            mock.patch.object(
                slack_connection,
                "_decrypt_ciphertext",
                return_value=plaintext,
            ),
            mock.patch.object(
                slack_connection,
                "_validate_slack_credentials",
                return_value=metadata,
            ),
            mock.patch.object(
                slack_connection,
                "_open_slack_home_channel",
                return_value="D012ABCDEF",
            ),
            mock.patch.object(
                slack_connection,
                "_set_hermes_secret",
                side_effect=lambda name, value: saved.append((name, value)),
            ),
            mock.patch.object(
                slack_connection,
                "_slack_api_call",
                side_effect=lambda method, **kwargs: (
                    slack_calls.append((method, kwargs)) or {"ok": True}
                ),
            ),
            mock.patch.object(
                slack_connection,
                "_send_secret_notice",
                side_effect=lambda text: notices.append(text),
            ),
            mock.patch.object(
                slack_connection,
                "_claim_handoff",
                side_effect=lambda *args, **kwargs: claims.append(kwargs),
            ),
        ):
            installed = slack_connection.install_submitted_slack_connection(
                client=object(),
                platform_auth="local_dev",
                handoff_id="sh_slack",
                private_key_pem="PRIVATE",
                state={"ciphertext_payload": {"algorithm": "RSA-OAEP-256"}},
            )

        self.assertTrue(installed)
        self.assertEqual(
            [name for name, _ in saved],
            [
                "SLACK_BOT_TOKEN",
                "SLACK_APP_TOKEN",
                "SLACK_ALLOWED_USERS",
                "SLACK_HOME_CHANNEL",
                "SLACK_HOME_CHANNEL_NAME",
            ],
        )
        self.assertEqual(
            saved[-2:],
            [
                ("SLACK_HOME_CHANNEL", "D012ABCDEF"),
                ("SLACK_HOME_CHANNEL_NAME", "Owner DM"),
            ],
        )
        self.assertEqual(
            claims[0]["connection_metadata"],
            {**metadata, "connection_status": "connected"},
        )
        self.assertEqual(
            claims[0]["outcome"],
            secret_handoff.HANDOFF_OUTCOME_RESTART_PENDING,
        )
        self.assertEqual(
            slack_calls,
            [
                (
                    "chat.postMessage",
                    {
                        "token": bot_token,
                        "params": {
                            "channel": "D012ABCDEF",
                            "text": slack_connection.SLACK_WELCOME_MESSAGE,
                        },
                        "stage": "greeting",
                    },
                )
            ],
        )
        self.assertEqual(notices, [])

    def test_slack_failure_reports_stage_to_telegram_and_platform(self) -> None:
        plaintext = json.dumps(
            {
                "schema": "tinyhat_slack_connection_bundle_v1",
                "bot_token": "xoxb-placeholder",
                "app_token": "xapp-placeholder",
                "allowed_users": "U012ABCDEF",
            }
        )
        claims: list[dict] = []
        notices: list[str] = []
        failure = slack_connection.SlackConnectionError(
            "Slack rejected users.info: user_not_found.",
            stage="member_lookup",
            code="user_not_found",
            public_message=(
                "Slack could not find an allowed member ID. Copy it from the "
                "member profile and retry."
            ),
        )
        with (
            mock.patch.object(
                slack_connection,
                "_decrypt_ciphertext",
                return_value=plaintext,
            ),
            mock.patch.object(
                slack_connection,
                "_validate_slack_credentials",
                side_effect=failure,
            ),
            mock.patch.object(
                slack_connection,
                "_send_secret_notice",
                side_effect=lambda text: notices.append(text),
            ),
            mock.patch.object(
                slack_connection,
                "_claim_handoff",
                side_effect=lambda *args, **kwargs: claims.append(kwargs),
            ),
            mock.patch.object(
                slack_connection,
                "_set_hermes_secret",
                side_effect=AssertionError("must not save failed details"),
            ),
        ):
            installed = slack_connection.install_submitted_slack_connection(
                client=object(),
                platform_auth="local_dev",
                handoff_id="sh_slack",
                private_key_pem="PRIVATE",
                state={"ciphertext_payload": {"algorithm": "RSA-OAEP-256"}},
            )

        self.assertFalse(installed)
        self.assertEqual(notices, [])
        self.assertEqual(claims[0]["installed"], False)
        self.assertEqual(
            claims[0]["connection_metadata"],
            {
                "provider": "slack",
                "connection_status": "failed",
                "failure_stage": "member_lookup",
                "failure_code": "user_not_found",
                "retryable": True,
            },
        )

    def test_slack_scope_failure_preserves_app_id_from_app_token(self) -> None:
        plaintext = json.dumps(
            {
                "schema": "tinyhat_slack_connection_bundle_v1",
                "bot_token": "xoxb-placeholder",
                "app_token": "xapp-1-A012ABCDEF-secret",
                "allowed_users": "U012ABCDEF",
            }
        )
        claims: list[dict] = []
        notices: list[str] = []
        failure = slack_connection.SlackConnectionError(
            "Slack rejected apps.connections.open: missing_scope.",
            stage="socket_mode",
            code="missing_scope",
            public_message=(
                "Slack needs updated permissions. Reinstall the app, then retry."
            ),
        )
        with (
            mock.patch.object(
                slack_connection,
                "_decrypt_ciphertext",
                return_value=plaintext,
            ),
            mock.patch.object(
                slack_connection,
                "_validate_slack_credentials",
                side_effect=failure,
            ),
            mock.patch.object(
                slack_connection,
                "_send_secret_notice",
                side_effect=lambda text: notices.append(text),
            ),
            mock.patch.object(
                slack_connection,
                "_claim_handoff",
                side_effect=lambda *args, **kwargs: claims.append(kwargs),
            ),
        ):
            installed = slack_connection.install_submitted_slack_connection(
                client=object(),
                platform_auth="local_dev",
                handoff_id="sh_slack",
                private_key_pem="PRIVATE",
                state={"ciphertext_payload": {"algorithm": "RSA-OAEP-256"}},
            )

        self.assertFalse(installed)
        self.assertEqual(
            claims[0]["connection_metadata"]["app_id"],
            "A012ABCDEF",
        )
        self.assertEqual(notices, [])

    def test_slack_greeting_failure_is_not_reported_as_connected(self) -> None:
        plaintext = json.dumps(
            {
                "schema": "tinyhat_slack_connection_bundle_v1",
                "bot_token": "xoxb-placeholder",
                "app_token": "xapp-placeholder",
                "allowed_users": "U012ABCDEF",
            }
        )
        metadata = {
            "provider": "slack",
            "app_id": "A012ABCDEF",
            "app_name": "Forecast Agent",
            "workspace_id": "T012ABCDEF",
            "workspace_name": "Tinyloop",
            "allowed_user_count": 1,
        }
        claims: list[dict] = []
        notices: list[str] = []
        greeting_failure = slack_connection.SlackConnectionError(
            "Slack rejected chat.postMessage: missing_scope.",
            stage="greeting",
            code="missing_scope",
            public_message=(
                "Slack needs updated permissions. Reinstall the app, then retry."
            ),
        )
        with (
            mock.patch.object(
                slack_connection,
                "_decrypt_ciphertext",
                return_value=plaintext,
            ),
            mock.patch.object(
                slack_connection,
                "_validate_slack_credentials",
                return_value=metadata,
            ),
            mock.patch.object(
                slack_connection,
                "_open_slack_home_channel",
                return_value="D012ABCDEF",
            ),
            mock.patch.object(slack_connection, "_set_hermes_secret"),
            mock.patch.object(
                slack_connection,
                "_slack_api_call",
                side_effect=greeting_failure,
            ),
            mock.patch.object(
                slack_connection,
                "_send_secret_notice",
                side_effect=lambda text: notices.append(text),
            ),
            mock.patch.object(
                slack_connection,
                "_claim_handoff",
                side_effect=lambda *args, **kwargs: claims.append(kwargs),
            ),
        ):
            installed = slack_connection.install_submitted_slack_connection(
                client=object(),
                platform_auth="local_dev",
                handoff_id="sh_slack",
                private_key_pem="PRIVATE",
                state={"ciphertext_payload": {"algorithm": "RSA-OAEP-256"}},
            )

        self.assertFalse(installed)
        self.assertNotIn(True, [claim["installed"] for claim in claims])
        self.assertEqual(claims[0]["installed"], False)
        self.assertEqual(
            claims[0]["connection_metadata"],
            {
                "provider": "slack",
                "app_id": "A012ABCDEF",
                "app_name": "Forecast Agent",
                "workspace_id": "T012ABCDEF",
                "workspace_name": "Tinyloop",
                "connection_status": "failed",
                "failure_stage": "greeting",
                "failure_code": "missing_scope",
                "retryable": True,
            },
        )
        self.assertEqual(notices, [])

    def test_slack_owner_dm_failure_notice_links_only_validated_app_id(
        self,
    ) -> None:
        failure = slack_connection.SlackConnectionError(
            "Slack rejected conversations.open: missing_scope.",
            stage="owner_dm",
            code="missing_scope",
            public_message="The submitted bot token cannot perform this Slack step.",
        )

        self.assertEqual(
            slack_connection._slack_failure_notice(
                failure,
                {"app_id": "a012abcdef"},
            ),
            (
                "Slack setup · Step 4 of 5. Reinstall the app once to apply the "
                "manifest permissions, then finish setup: "
                "https://api.slack.com/apps/A012ABCDEF/install-on-team"
            ),
        )
        self.assertNotIn(
            "api.slack.com/apps",
            slack_connection._slack_failure_notice(
                failure,
                {"app_id": "https://example.test/not-an-app"},
            ),
        )

    def test_slack_owner_dm_non_scope_failure_does_not_request_reinstall(
        self,
    ) -> None:
        failure = slack_connection.SlackConnectionError(
            "Slack rejected conversations.open: user_not_found.",
            stage="owner_dm",
            code="user_not_found",
            public_message="Slack could not open the owner's direct message.",
        )

        notice = slack_connection._slack_failure_notice(
            failure,
            {"app_id": "A012ABCDEF"},
        )

        self.assertEqual(
            notice,
            (
                "Slack connection failed during owner direct-message setup. "
                "Slack could not open the owner's direct message. "
                "Open the Slack app: https://api.slack.com/apps/A012ABCDEF"
            ),
        )
        self.assertNotIn("reinstall", notice)

    def test_slack_failure_claim_retries_without_metadata_for_old_platform(
        self,
    ) -> None:
        plaintext = json.dumps(
            {
                "schema": "tinyhat_slack_connection_bundle_v1",
                "bot_token": "xoxb-placeholder",
                "app_token": "xapp-placeholder",
                "allowed_users": "U012ABCDEF",
            }
        )
        failure = slack_connection.SlackConnectionError(
            "Slack rejected auth.test: invalid_auth.",
            stage="bot_auth",
            code="invalid_auth",
            public_message=(
                "Slack did not accept the bot token. Copy the xoxb token and retry."
            ),
        )
        claims: list[dict] = []

        def fake_claim(*_args, **kwargs):
            claims.append(kwargs)
            if len(claims) == 1:
                raise RuntimeError("old platform rejected failure metadata")

        with (
            mock.patch.object(
                slack_connection,
                "_decrypt_ciphertext",
                return_value=plaintext,
            ),
            mock.patch.object(
                slack_connection,
                "_validate_slack_credentials",
                side_effect=failure,
            ),
            mock.patch.object(
                slack_connection, "_send_secret_notice"
            ) as send_notice,
            mock.patch.object(
                slack_connection,
                "_claim_handoff",
                side_effect=fake_claim,
            ),
        ):
            installed = slack_connection.install_submitted_slack_connection(
                client=object(),
                platform_auth="local_dev",
                handoff_id="sh_slack",
                private_key_pem="PRIVATE",
                state={"ciphertext_payload": {"algorithm": "RSA-OAEP-256"}},
            )

        self.assertFalse(installed)
        self.assertEqual(len(claims), 2)
        send_notice.assert_called_once()
        self.assertIn("Slack connection failed", send_notice.call_args.args[0])
        self.assertEqual(claims[0]["installed"], False)
        self.assertEqual(
            claims[0]["connection_metadata"]["failure_code"],
            "invalid_auth",
        )
        self.assertEqual(
            claims[1],
            {
                "installed": False,
                "message": (
                    "Slack did not accept the bot token. "
                    "Copy the xoxb token and retry."
                ),
            },
        )

    def test_slack_bundle_parser_rejects_schema_and_token_prefixes(self) -> None:
        cases = (
            (
                {"schema": "wrong", "bot_token": "xoxb-ok", "app_token": "xapp-ok"},
                "schema",
            ),
            (
                {
                    "schema": "tinyhat_slack_connection_bundle_v1",
                    "bot_token": "xoxp-wrong",
                    "app_token": "xapp-ok",
                    "allowed_users": "U012ABCDEF",
                },
                "bot token",
            ),
            (
                {
                    "schema": "tinyhat_slack_connection_bundle_v1",
                    "bot_token": "xoxb-ok",
                    "app_token": "xoxb-wrong",
                    "allowed_users": "U012ABCDEF",
                },
                "app token",
            ),
        )
        for payload, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                secret_handoff.SecretHandoffError,
                message,
            ):
                slack_connection._parse_connection_bundle(json.dumps(payload))

    def test_slack_allowed_users_are_normalized_deduplicated_and_bounded(self) -> None:
        self.assertEqual(
            slack_connection._normalize_allowed_users(" u012abcdef, U012ABCDEF, w012abcdef "),
            "U012ABCDEF,W012ABCDEF",
        )
        for value in (
            "",
            "not-a-member-id",
            ",".join(f"U{i:09d}" for i in range(101)),
        ):
            with self.subTest(value=value[:40]), self.assertRaisesRegex(
                secret_handoff.SecretHandoffError,
                "member IDs",
            ):
                slack_connection._normalize_allowed_users(value)

    def test_slack_home_channel_uses_first_allowed_member_dm(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_slack_call(method: str, **kwargs):
            calls.append((method, kwargs))
            return {"channel": {"id": "d012abcdef"}}

        with mock.patch.object(
            slack_connection,
            "_slack_api_call",
            side_effect=fake_slack_call,
        ):
            channel_id = slack_connection._open_slack_home_channel(
                {
                    "bot_token": "xoxb-placeholder",
                    "allowed_users": "U012ABCDEF,U999ABCDEF",
                }
            )

        self.assertEqual(channel_id, "D012ABCDEF")
        self.assertEqual(
            calls,
            [
                (
                    "conversations.open",
                    {
                        "token": "xoxb-placeholder",
                        "params": {"users": "U012ABCDEF"},
                        "stage": "owner_dm",
                    },
                )
            ],
        )

    def test_slack_home_channel_rejects_missing_dm_id(self) -> None:
        with (
            mock.patch.object(
                slack_connection,
                "_slack_api_call",
                return_value={"channel": {}},
            ),
            self.assertRaisesRegex(
                secret_handoff.SecretHandoffError,
                "direct-message channel",
            ),
        ):
            slack_connection._open_slack_home_channel(
                {
                    "bot_token": "xoxb-placeholder",
                    "allowed_users": "U012ABCDEF",
                }
            )

    def test_slack_validation_uses_auth_metadata_without_user_lookup(self) -> None:
        bundle = {
            "bot_token": "xoxb-placeholder",
            "app_token": "xapp-placeholder",
            "allowed_users": "U012ABCDEF",
        }
        calls: list[str] = []

        def fake_slack_call(method: str, **kwargs):
            del kwargs
            calls.append(method)
            if method == "auth.test":
                return {
                    "app_id": "A012ABCDEF",
                    "team_id": "T012ABCDEF",
                    "team": "Tinyloop",
                    "user": "The Forecaster",
                }
            return {"ok": True}

        with mock.patch.object(
            slack_connection,
            "_slack_api_call",
            side_effect=fake_slack_call,
        ):
            metadata = slack_connection._validate_slack_credentials(bundle)
        self.assertEqual(metadata["app_id"], "A012ABCDEF")
        self.assertEqual(metadata["app_name"], "The Forecaster")
        self.assertEqual(calls, ["auth.test", "apps.connections.open"])

    def test_slack_validation_does_not_require_optional_app_lookup(self) -> None:
        bundle = {
            "bot_token": "xoxb-placeholder",
            "app_token": "xapp-placeholder",
            "allowed_users": "U012ABCDEF",
        }
        calls: list[str] = []

        def fake_slack_call(method: str, **kwargs):
            del kwargs
            calls.append(method)
            if method == "auth.test":
                return {
                    "team_id": "T012ABCDEF",
                    "team": "Tinyloop",
                    "user": "The Forecaster",
                    "bot_id": "B012ABCDEF",
                }
            if method == "bots.info":
                raise slack_connection.SlackConnectionError(
                    "Slack rejected bots.info: missing_scope",
                    stage="app_identity",
                    code="missing_scope",
                    public_message="Optional app lookup was unavailable.",
                )
            return {"ok": True}

        with mock.patch.object(
            slack_connection,
            "_slack_api_call",
            side_effect=fake_slack_call,
        ):
            metadata = slack_connection._validate_slack_credentials(bundle)

        self.assertNotIn("app_id", metadata)
        self.assertEqual(metadata["workspace_id"], "T012ABCDEF")
        self.assertEqual(
            calls,
            ["auth.test", "apps.connections.open", "bots.info"],
        )

    def test_slack_validation_uses_app_id_embedded_in_app_token(self) -> None:
        bundle = {
            "bot_token": "xoxb-placeholder",
            "app_token": "xapp-1-A012ABCDEF-secret",
            "allowed_users": "U012ABCDEF",
        }
        calls: list[str] = []

        def fake_slack_call(method: str, **kwargs):
            del kwargs
            calls.append(method)
            if method == "auth.test":
                return {
                    "team_id": "T012ABCDEF",
                    "team": "Tinyloop",
                    "user": "The Forecaster",
                    "bot_id": "B012ABCDEF",
                }
            return {"ok": True}

        with mock.patch.object(
            slack_connection,
            "_slack_api_call",
            side_effect=fake_slack_call,
        ):
            metadata = slack_connection._validate_slack_credentials(bundle)

        self.assertEqual(metadata["app_id"], "A012ABCDEF")
        self.assertEqual(calls, ["auth.test", "apps.connections.open"])

    def test_slack_app_token_app_id_parser_rejects_unrecognized_shapes(
        self,
    ) -> None:
        self.assertEqual(
            slack_connection._app_id_from_app_token(
                "xapp-1-a012abcdef-secret"
            ),
            "A012ABCDEF",
        )
        for value in (
            "xapp-placeholder",
            "xapp-1-T012ABCDEF-secret",
            "xoxb-1-A012ABCDEF-secret",
            "",
        ):
            with self.subTest(value=value):
                self.assertIsNone(
                    slack_connection._app_id_from_app_token(value)
                )

    def test_slack_api_call_maps_transport_and_slack_errors(self) -> None:
        with (
            mock.patch.object(
                slack_connection.request,
                "urlopen",
                side_effect=error.URLError("offline"),
            ),
            self.assertRaises(slack_connection.SlackConnectionError) as raised,
        ):
            slack_connection._slack_api_call(
                "conversations.open",
                token="xoxb-placeholder",
                stage="owner_dm",
            )
        self.assertEqual(raised.exception.stage, "owner_dm")
        self.assertEqual(raised.exception.code, "network_error")
        self.assertIn("could not be reached", raised.exception.public_message)

        cases = (
            ("invalid_auth", "bot_auth", "invalid_auth"),
            ("not_allowed_token_type", "socket_mode", "not_allowed_token_type"),
            ("missing_scope", "bot_auth", "missing_scope"),
            ("user_not_found", "member_lookup", "user_not_found"),
            ("cannot_dm_user", "owner_dm", "cannot_dm_user"),
            ("ratelimited", "owner_dm", "slack_rejected"),
        )
        for provider_code, stage, expected_code in cases:
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(
                {"ok": False, "error": provider_code}
            ).encode()
            with (
                self.subTest(provider_code=provider_code),
                mock.patch.object(
                    slack_connection.request,
                    "urlopen",
                    return_value=response,
                ),
                self.assertRaises(
                    slack_connection.SlackConnectionError
                ) as raised,
            ):
                slack_connection._slack_api_call(
                    "auth.test",
                    token="xoxb-placeholder",
                    stage=stage,
                )
            self.assertEqual(raised.exception.stage, stage)
            self.assertEqual(raised.exception.code, expected_code)

    def test_slack_manifest_error_keeps_redaction_safe_stderr_tail(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hermes"],
            returncode=2,
            stdout="",
            stderr="manifest flag is unavailable",
        )
        with (
            mock.patch.object(slack_connection.shutil, "which", return_value="/bin/hermes"),
            mock.patch.object(slack_connection.subprocess, "run", return_value=completed),
            self.assertRaisesRegex(
                secret_handoff.SecretHandoffError,
                "manifest flag is unavailable",
            ),
        ):
            slack_connection._generate_hermes_slack_manifest()

    def test_slack_manifest_removes_workspace_global_slash_commands(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["hermes"],
            returncode=0,
            stdout=json.dumps(
                {
                    "features": {
                        "agent_view": {"agent_description": "Hermes"},
                        "slash_commands": [
                            {"command": "/hermes"},
                            {"command": "/model"},
                        ],
                    },
                    "oauth_config": {
                        "scopes": {
                            "bot": [
                                "assistant:write",
                                "chat:write",
                                "commands",
                                "users:read",
                            ]
                        }
                    },
                    "settings": {"socket_mode_enabled": True},
                }
            ),
            stderr="",
        )
        with (
            mock.patch.object(slack_connection.shutil, "which", return_value="/bin/hermes"),
            mock.patch.object(slack_connection.subprocess, "run", return_value=completed),
        ):
            manifest = slack_connection._generate_hermes_slack_manifest()

        self.assertNotIn("slash_commands", manifest["features"])
        self.assertEqual(
            manifest["oauth_config"]["scopes"]["bot"],
            ["assistant:write", "chat:write", "users:read", "im:write"],
        )

    def test_generic_secret_flow_refuses_reserved_slack_connection_values(self) -> None:
        for name in secret_handoff.RESERVED_SLACK_CONNECTION_NAMES:
            with self.subTest(name=name):
                payload = json.loads(
                    secret_handoff.start_private_secret_handoff(
                        {
                            "name": name,
                            "description": "Slack connection value.",
                        }
                    )
                )
                self.assertEqual(payload["error"], "slack_connection_required")
                self.assertIn("tinyhat_slack_connect", payload["message"])

    def test_generic_installer_refuses_slack_bundle_name_under_version_skew(self) -> None:
        with (
            mock.patch.object(
                secret_handoff,
                "_decrypt_ciphertext",
                side_effect=AssertionError("must reject before decrypting"),
            ),
            self.assertRaisesRegex(
                secret_handoff.SecretHandoffError,
                "Reserved Slack connection",
            ),
        ):
            secret_handoff._install_submitted_secret(
                client=object(),
                platform_auth="local_dev",
                handoff_id="sh_slack",
                private_key_pem="PRIVATE",
                state={
                    "secret_name": "SLACK_CONNECTION",
                    "ciphertext_payload": {"algorithm": "RSA-OAEP-256"},
                },
            )

    def test_private_secret_handoff_missing_params_error_is_actionable(self) -> None:
        payload = json.loads(tools.private_secret_handoff({}))

        self.assertEqual(payload["schema"], "tinyhat_tool_error_v1")
        self.assertEqual(payload["tool"], "tinyhat_private_secret_handoff")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "missing_required_parameter")
        self.assertEqual(payload["missing"], ["name", "description"])
        self.assertEqual(
            payload["example_call"],
            {
                "name": "EXA_API_KEY",
                "description": "Exa API key for web search and research tools.",
            },
        )

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
            secret_handoff._start_worker_process = lambda handoff, private_key_pem: (
                worker_calls.append({"handoff": handoff, "private_key_pem": private_key_pem})
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

    def test_private_secret_handoff_rejects_secret_name_alias(self) -> None:
        payload = json.loads(
            tools.private_secret_handoff(
                {
                    "secret_name": "EXA_API_KEY",
                    "description": "Exa API key for search research",
                }
            )
        )

        self.assertEqual(payload["schema"], "tinyhat_tool_error_v1")
        self.assertEqual(payload["error"], "missing_required_parameter")
        self.assertEqual(payload["missing"], ["name"])
        self.assertEqual(
            payload["example_call"],
            {
                "name": "EXA_API_KEY",
                "description": "Exa API key for web search and research tools.",
            },
        )

    def test_context_prefers_codex_auth_tool_actions(self) -> None:
        self.assertIn(
            "prefer tinyhat_codex_auth with action=status",
            tinyhat_context.TINYHAT_CONTEXT,
        )
        self.assertNotIn(
            "prefer the Tinyhat-installed /codex_auth",
            tinyhat_context.TINYHAT_CONTEXT,
        )

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
            secret_handoff._start_worker_process = lambda handoff, private_key_pem: (
                worker_calls.append({"handoff": handoff, "private_key_pem": private_key_pem})
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
        original_register = secret_handoff._register_terminal_env_secret
        original_notice = secret_handoff._send_secret_available_notice
        try:
            secret_handoff._decrypt_ciphertext = lambda *_: "super-secret-value"
            secret_handoff._set_hermes_secret = lambda name, value: events.append(("set", name))
            secret_handoff._register_terminal_env_secret = lambda name: (
                events.append(("register", name)) or {"ok": True}
            )
            secret_handoff._send_secret_available_notice = lambda name: (
                events.append(("notice", name)) or {"sent": True, "ok": True}
            )

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
            secret_handoff._register_terminal_env_secret = original_register
            secret_handoff._send_secret_available_notice = original_notice

        self.assertEqual(
            events,
            [
                ("set", "EXA_API_KEY"),
                ("register", "EXA_API_KEY"),
                ("notice", "EXA_API_KEY"),
                ("claim", True),
            ],
        )
        self.assertEqual(
            fake_client.claim_payloads[-1],
            {
                "installed": True,
                "message": None,
                "outcome": "installed_restart_pending",
            },
        )
        self.assertNotIn("gateway_ready", fake_client.claim_payloads[-1])
        self.assertNotIn("super-secret-value", json.dumps(fake_client.claim_payloads))

    def test_private_secret_claim_retries_legacy_payload_for_old_platform(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.claim_payloads: list[dict] = []

            def post_json(self, path: str, payload: dict) -> dict:
                self.claim_payloads.append(payload)
                if "outcome" in payload:
                    raise RuntimeError("unexpected field: outcome")
                return {"status": "claimed"}

        fake_client = FakeClient()
        secret_handoff._claim_handoff(
            fake_client,
            "local_dev",
            "sh_test",
            installed=True,
            message=None,
            outcome=secret_handoff.HANDOFF_OUTCOME_RESTART_PENDING,
        )

        self.assertEqual(
            fake_client.claim_payloads,
            [
                {
                    "installed": True,
                    "message": None,
                    "outcome": "installed_restart_pending",
                },
                {
                    "installed": True,
                    "message": None,
                },
            ],
        )

    def test_private_secret_install_never_restarts_gateway_itself(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.claim_payloads: list[dict] = []

            def post_json(self, path: str, payload: dict) -> dict:
                self.claim_payloads.append(payload)
                return {"status": "claimed"}

        fake_client = FakeClient()
        subprocess_calls: list[list[str]] = []
        popen_calls: list[object] = []

        def fake_run(args, **kwargs):
            subprocess_calls.append([str(part) for part in args])
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")

        original_decrypt = secret_handoff._decrypt_ciphertext
        original_set = secret_handoff._set_hermes_secret
        original_notice = secret_handoff._send_secret_notice
        original_run = secret_handoff.subprocess.run
        original_popen = secret_handoff.subprocess.Popen
        try:
            secret_handoff._decrypt_ciphertext = lambda *_: "super-secret-value"
            secret_handoff._set_hermes_secret = lambda name, value: None
            secret_handoff._send_secret_notice = lambda text: {"sent": True, "ok": True}
            secret_handoff.subprocess.run = fake_run
            secret_handoff.subprocess.Popen = lambda *args, **kwargs: popen_calls.append(args)

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
            secret_handoff._send_secret_notice = original_notice
            secret_handoff.subprocess.run = original_run
            secret_handoff.subprocess.Popen = original_popen

        flattened = " ".join(" ".join(call) for call in subprocess_calls)
        self.assertNotIn("stop_hermes", flattened)
        self.assertNotIn("start_hermes", flattened)
        self.assertEqual(popen_calls, [])
        self.assertEqual(
            fake_client.claim_payloads[-1],
            {
                "installed": True,
                "message": None,
                "outcome": "installed_restart_pending",
            },
        )

    def test_private_secret_worker_prefers_systemd_survivor_unit(self) -> None:
        original_which = secret_handoff.shutil.which
        original_run = secret_handoff.subprocess.run
        commands: list[dict[str, object]] = []

        def fake_run(args, **kwargs):
            commands.append({"args": args, **kwargs})
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "private.pem"
            key_path.write_text("PRIVATE", encoding="utf-8")
            package_dir = Path(tmp) / "tinyhat"
            package_dir.mkdir()
            env = {
                "PATH": "/usr/bin",
                "PYTHONPATH": "/tmp/pkg",
                "HERMES_PROJECT_DIR": "/home/tinyhat/project",
                "TINYHAT_HERMES_HOME": "/home/tinyhat/.hermes",
                "TINYHAT_PLATFORM_URL": "http://localhost:8000",
                "TINYHAT_LOCAL_DEV_TOKEN": "dev-token",
            }
            try:
                secret_handoff.shutil.which = lambda name: (
                    "/usr/bin/systemd-run" if name == "systemd-run" else None
                )
                secret_handoff.subprocess.run = fake_run

                started = secret_handoff._start_worker_with_systemd(
                    handoff_id="sh_test",
                    key_path=key_path,
                    package_dir=package_dir,
                    env=env,
                    expires_in_seconds=30 * 60,
                )
            finally:
                secret_handoff.shutil.which = original_which
                secret_handoff.subprocess.run = original_run

        self.assertTrue(started)
        args = commands[0]["args"]
        self.assertIn("--user", args)
        self.assertIn("--collect", args)
        self.assertIn("--setenv=HERMES_PROJECT_DIR=/home/tinyhat/project", args)
        self.assertIn("--setenv=TINYHAT_HERMES_HOME=/home/tinyhat/.hermes", args)
        self.assertIn("--setenv=TINYHAT_PLATFORM_URL=http://localhost:8000", args)
        self.assertIn("--setenv=TINYHAT_LOCAL_DEV_TOKEN=dev-token", args)
        self.assertIn("--expires-in-seconds", args)
        self.assertIn(str(30 * 60), args)

    def test_private_secret_worker_systemd_failure_falls_back_to_popen(self) -> None:
        original_which = secret_handoff.shutil.which
        original_run = secret_handoff.subprocess.run
        original_popen = secret_handoff.subprocess.Popen
        original_state_dir = secret_handoff.STATE_DIR
        run_calls: list[object] = []
        popen_calls: list[dict[str, object]] = []

        def fake_run(args, **kwargs):
            run_calls.append(args)
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="Failed to start transient service unit",
            )

        def fake_popen(args, **kwargs):
            popen_calls.append({"args": args, **kwargs})
            return object()

        with tempfile.TemporaryDirectory() as tmp:
            try:
                secret_handoff.STATE_DIR = Path(tmp) / "handoffs"
                secret_handoff.shutil.which = lambda name: (
                    "/usr/bin/systemd-run" if name == "systemd-run" else None
                )
                secret_handoff.subprocess.run = fake_run
                secret_handoff.subprocess.Popen = fake_popen

                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    secret_handoff._start_worker_process(
                        {
                            "handoff_id": "sh_test",
                            "entry_window_seconds": 30 * 60,
                        },
                        "PRIVATE",
                    )
            finally:
                secret_handoff.STATE_DIR = original_state_dir
                secret_handoff.shutil.which = original_which
                secret_handoff.subprocess.run = original_run
                secret_handoff.subprocess.Popen = original_popen

        self.assertEqual(len(run_calls), 1)
        self.assertIn("systemd-run", run_calls[0][0])
        self.assertEqual(len(popen_calls), 1)
        worker_args = popen_calls[0]["args"]
        self.assertTrue(str(worker_args[1]).endswith("secret_handoff_worker.py"))
        self.assertIn("--handoff-id", worker_args)
        self.assertIn("sh_test", worker_args)
        self.assertIn("--expires-in-seconds", worker_args)
        self.assertIn(str(30 * 60), worker_args)
        self.assertIn("falling back to a detached process", stderr.getvalue())
        self.assertIn("Failed to start transient service unit", stderr.getvalue())

    def test_private_secret_worker_uses_platform_entry_window(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(
                secret_handoff,
                "STATE_DIR",
                Path(tmp) / "handoffs",
            ),
            mock.patch.object(
                secret_handoff,
                "_start_worker_with_systemd",
                return_value=True,
            ) as start_worker,
        ):
            secret_handoff._start_worker_process(
                {
                    "handoff_id": "sh_slack",
                    "entry_window_seconds": 30 * 60,
                },
                "PRIVATE",
            )

        self.assertEqual(
            start_worker.call_args.kwargs["expires_in_seconds"],
            30 * 60,
        )

    def test_private_secret_save_ignores_worker_reload_failure(self) -> None:
        original_which = secret_handoff.shutil.which
        original_run = secret_handoff._run
        original_reload = secret_handoff._reload_hermes_env_current_process
        calls: list[dict[str, object]] = []

        try:
            secret_handoff.shutil.which = lambda name: (
                "/usr/bin/hermes" if name == "hermes" else None
            )
            secret_handoff._run = lambda args, **kwargs: calls.append({"args": args, **kwargs})
            secret_handoff._reload_hermes_env_current_process = lambda *_: (_ for _ in ()).throw(
                RuntimeError("reload failed")
            )

            secret_handoff._set_hermes_secret("EXA_API_KEY", "super-secret-value")
        finally:
            secret_handoff.shutil.which = original_which
            secret_handoff._run = original_run
            secret_handoff._reload_hermes_env_current_process = original_reload

        self.assertEqual(calls[0]["args"][:3], ["/usr/bin/hermes", "config", "set"])
        self.assertEqual(calls[0]["redactions"], ("super-secret-value",))

    def test_hermes_python_executable_prefers_production_wrapper_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "usr" / "local" / "bin"
            project_dir = root / "usr" / "local" / "lib" / "hermes-agent"
            wrapper = bin_dir / "hermes"
            runtime_python = project_dir / "venv" / "bin" / "python"
            unrelated_python = bin_dir / "python3"
            runtime_python.parent.mkdir(parents=True)
            bin_dir.mkdir(parents=True)
            runtime_python.touch()
            unrelated_python.touch()
            wrapper.write_text(
                "#!/bin/sh\n"
                f'exec "{runtime_python}" -m hermes_cli.main "$@"\n',
                encoding="utf-8",
            )

            with mock.patch.object(
                secret_handoff,
                "_python_can_import_hermes_cli",
                return_value=True,
            ) as probe:
                resolved = secret_handoff._hermes_python_executable(str(wrapper))

        self.assertEqual(resolved, str(runtime_python))
        probe.assert_called_once_with(runtime_python)

    def test_hermes_python_executable_uses_explicit_project_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wrapper = root / "bin" / "hermes"
            project_dir = root / "hermes-agent"
            runtime_python = project_dir / "venv" / "bin" / "python"
            wrapper.parent.mkdir(parents=True)
            runtime_python.parent.mkdir(parents=True)
            wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            runtime_python.touch()

            with (
                mock.patch.dict(
                    os.environ,
                    {"HERMES_PROJECT_DIR": str(project_dir)},
                ),
                mock.patch.object(
                    secret_handoff,
                    "_python_can_import_hermes_cli",
                    return_value=True,
                ) as probe,
            ):
                resolved = secret_handoff._hermes_python_executable(str(wrapper))

        self.assertEqual(resolved, str(runtime_python))
        probe.assert_called_once_with(runtime_python)

    def test_save_hermes_env_value_uses_runtime_python_and_stdin(self) -> None:
        calls: list[dict[str, object]] = []
        runtime_python = "/opt/hermes-agent/venv/bin/python"
        allowed_users = "U0123456789"

        with (
            mock.patch.object(
                secret_handoff,
                "_hermes_python_executable",
                return_value=runtime_python,
            ),
            mock.patch.object(
                secret_handoff,
                "_run",
                side_effect=lambda args, **kwargs: calls.append(
                    {"args": args, **kwargs}
                ),
            ),
        ):
            secret_handoff._save_hermes_env_value(
                "/usr/local/bin/hermes",
                "SLACK_ALLOWED_USERS",
                allowed_users,
            )

        self.assertEqual(calls[0]["args"][0], runtime_python)
        self.assertEqual(calls[0]["args"][1], "-c")
        self.assertEqual(calls[0]["args"][-1], "SLACK_ALLOWED_USERS")
        self.assertEqual(calls[0]["input_text"], allowed_users)
        self.assertEqual(calls[0]["redactions"], (allowed_users,))
        self.assertNotIn(allowed_users, calls[0]["args"])

    def test_register_terminal_env_secret_calls_runtime_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_prefix = Path(tmp) / "runtime"
            package = runtime_prefix / "hermes_runtime"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            marker = Path(tmp) / "register-call.json"
            (package / "terminal_env_passthrough.py").write_text(
                "import json, pathlib, sys\n"
                f"pathlib.Path({str(marker)!r}).write_text("
                "json.dumps(sys.argv[1:]), encoding='utf-8')\n"
                "print(json.dumps({'added': True}))\n",
                encoding="utf-8",
            )
            original_prefix = os.environ.get("TINYHAT_RUNTIME_PREFIX")
            os.environ["TINYHAT_RUNTIME_PREFIX"] = str(runtime_prefix)
            try:
                result = secret_handoff._register_terminal_env_secret("EXA_API_KEY")
            finally:
                if original_prefix is None:
                    os.environ.pop("TINYHAT_RUNTIME_PREFIX", None)
                else:
                    os.environ["TINYHAT_RUNTIME_PREFIX"] = original_prefix

            self.assertTrue(result["ok"])
            self.assertEqual(
                json.loads(marker.read_text(encoding="utf-8")),
                ["register", "EXA_API_KEY"],
            )

    def test_register_terminal_env_secret_is_best_effort_without_runtime(self) -> None:
        original_prefix = os.environ.get("TINYHAT_RUNTIME_PREFIX")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TINYHAT_RUNTIME_PREFIX"] = str(Path(tmp) / "missing")
            try:
                result = secret_handoff._register_terminal_env_secret("EXA_API_KEY")
            finally:
                if original_prefix is None:
                    os.environ.pop("TINYHAT_RUNTIME_PREFIX", None)
                else:
                    os.environ["TINYHAT_RUNTIME_PREFIX"] = original_prefix

        self.assertFalse(result["ok"])
        self.assertTrue(result["error"])

    def test_private_secret_notice_is_plain_text_and_best_effort(self) -> None:
        original_credentials = tools._telegram_credentials
        original_send = tools._telegram_send_message
        sent_messages: list[str] = []

        try:
            tools._telegram_credentials = lambda: ("token", "chat")
            tools._telegram_send_message = lambda **kwargs: (
                sent_messages.append(kwargs["text"]) or {"ok": True}
            )

            result = secret_handoff._send_secret_available_notice("EXA_API_KEY")
        finally:
            tools._telegram_credentials = original_credentials
            tools._telegram_send_message = original_send

        self.assertEqual(result, {"sent": True, "ok": True})
        self.assertEqual(
            sent_messages[-1],
            (
                "EXA_API_KEY is saved. The platform is refreshing my Telegram "
                "gateway now — I will confirm when it is ready."
            ),
        )
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
            secret_handoff_worker._install_submitted_secret = lambda **_: (_ for _ in ()).throw(
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

    def test_slack_worker_keeps_private_key_for_same_handoff_retry(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.states = iter(
                    [
                        {
                            "status": "submitted",
                            "handoff_kind": "slack_connection",
                        },
                        {
                            "status": "failed",
                            "handoff_kind": "slack_connection",
                        },
                        {
                            "status": "pending",
                            "handoff_kind": "slack_connection",
                        },
                        {
                            "status": "submitted",
                            "handoff_kind": "slack_connection",
                        },
                    ]
                )

            def get_json(self, path: str) -> dict:
                del path
                return next(self.states)

        install_results = iter([False, True])
        install_calls: list[dict] = []
        with (
            mock.patch.object(
                secret_handoff_worker,
                "build_platform_client",
                return_value=(FakeClient(), "local_dev"),
            ),
            mock.patch.object(
                secret_handoff_worker,
                "_install_submitted_secret",
                side_effect=lambda **kwargs: (
                    install_calls.append(kwargs) or next(install_results)
                ),
            ),
            mock.patch.object(secret_handoff_worker.time, "sleep"),
            tempfile.TemporaryDirectory(prefix="tinyhat-worker-retry-") as temp_dir,
        ):
            key_path = Path(temp_dir) / "private.pem"
            key_path.write_text("PRIVATE", encoding="utf-8")

            secret_handoff_worker.run_worker(
                handoff_id="sh_slack_retry",
                key_path=key_path,
            )

            self.assertFalse(key_path.exists())

        self.assertEqual(len(install_calls), 2)
        self.assertEqual(
            [call["state"]["status"] for call in install_calls],
            ["submitted", "submitted"],
        )

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
        payload = json.loads(tools.tell_joke({"topic": "Hermes"}, task_id="task_123"))

        self.assertEqual(payload["schema"], "tinyhat_tell_joke_v1")
        self.assertIn("Hermes", payload["joke"])


class PlatformClientTests(unittest.TestCase):
    def test_http_error_preserves_structured_policy_details(self) -> None:
        response = {
            "detail": {
                "error": "google_workspace_scope_review_required",
                "manifest_version": "1.0.1",
                "blocked_scopes": ["https://www.googleapis.com/auth/tasks"],
            }
        }
        http_error = error.HTTPError(
            url="https://api.example.test/path",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(json.dumps(response).encode("utf-8")),
        )
        client = platform.PlatformClient(
            base_url="https://api.example.test",
            token="local-token",
        )

        with (
            mock.patch.object(platform.request, "urlopen", side_effect=http_error),
            self.assertRaises(platform.PlatformError) as raised,
        ):
            client.post_json("/path", {"value": 1})

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.response, response)


if __name__ == "__main__":
    unittest.main()
