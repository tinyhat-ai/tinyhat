"""Tests for the read-only Tinyhat credit tool."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))

from tinyhat import credit, platform  # noqa: E402
from tinyhat.platform import PlatformError  # noqa: E402


class CreditToolTests(unittest.TestCase):
    def test_openclaw_runtime_uses_its_platform_contract(self) -> None:
        client, platform_auth = platform.build_platform_client(
            {
                "TINYHAT_PLATFORM_BASE_URL": "https://platform.test",
                "TINYHAT_BACKEND_AUDIENCE": "https://audience.test",
                "TINYHAT_DEV_RUNTIME": "1",
            }
        )

        self.assertEqual(client.base_url, "https://platform.test")
        self.assertEqual(client.token, "dev-runtime")
        self.assertIsNone(client.token_provider)
        self.assertEqual(platform_auth, "gcloud")

    def test_openclaw_production_uses_backend_audience(self) -> None:
        client, platform_auth = platform.build_platform_client(
            {
                "TINYHAT_PLATFORM_BASE_URL": "https://platform.test",
                "TINYHAT_BACKEND_AUDIENCE": "https://audience.test",
            }
        )

        self.assertEqual(client.base_url, "https://platform.test")
        self.assertIsInstance(
            client.token_provider,
            platform.CachedGoogleIdentityToken,
        )
        self.assertEqual(client.token_provider.audience, "https://audience.test")
        self.assertEqual(platform_auth, "gcloud")

    def test_openclaw_production_reads_runtime_environment_file(self) -> None:
        original_env_files = platform.DEFAULT_ENV_FILES
        try:
            with tempfile.TemporaryDirectory() as tmp:
                runtime_env_file = Path(tmp) / "runtime.env"
                runtime_env_file.write_text(
                    "TINYHAT_PLATFORM_BASE_URL=https://platform.test\n"
                    "TINYHAT_BACKEND_AUDIENCE=https://audience.test\n",
                    encoding="utf-8",
                )
                platform.DEFAULT_ENV_FILES = (runtime_env_file,)
                client, platform_auth = platform.build_platform_client({})
        finally:
            platform.DEFAULT_ENV_FILES = original_env_files

        self.assertEqual(client.base_url, "https://platform.test")
        self.assertIsInstance(
            client.token_provider,
            platform.CachedGoogleIdentityToken,
        )
        self.assertEqual(client.token_provider.audience, "https://audience.test")
        self.assertEqual(platform_auth, "gcloud")

    def test_openclaw_skill_fallback_supports_production_state_dir(self) -> None:
        skill = (REPO_ROOT / "skills" / "tinyhat-credit" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '${TINYHAT_RUNTIME_HOME:-$OPENCLAW_STATE_DIR}/extensions',
            skill,
        )

    def test_reads_owner_summary_from_attested_computer_route(self) -> None:
        original_build = credit.build_platform_client
        paths: list[str] = []

        class FakeClient:
            def get_json(self, path: str) -> dict[str, object]:
                paths.append(path)
                return {
                    "schema": "tinyhat_credit_summary_v1",
                    "balance_cents": 2550,
                    "currency": "usd",
                    "recent_transactions": [
                        {
                            "entry_type": "top_up",
                            "amount_cents": 2550,
                            "currency": "usd",
                            "created_at": "2026-08-15T18:30:00Z",
                            "stripe_checkout_session_id": "must-not-leak",
                        }
                    ],
                    "stripe_customer_id": "must-not-leak",
                }

        try:
            credit.build_platform_client = lambda: (FakeClient(), "gcloud")
            payload = json.loads(credit.credit_summary())
        finally:
            credit.build_platform_client = original_build

        self.assertEqual(paths, ["/hapi/v1/computers/me/credit/v1"])
        self.assertEqual(payload["balance_cents"], 2550)
        self.assertEqual(len(payload["recent_transactions"]), 1)
        self.assertNotIn("stripe_customer_id", payload)
        self.assertNotIn(
            "stripe_checkout_session_id",
            payload["recent_transactions"][0],
        )

    def test_uses_local_computer_route(self) -> None:
        original_build = credit.build_platform_client
        paths: list[str] = []

        class FakeClient:
            def get_json(self, path: str) -> dict[str, object]:
                paths.append(path)
                return {
                    "balance_cents": 0,
                    "currency": "usd",
                    "recent_transactions": [],
                }

        try:
            credit.build_platform_client = lambda: (FakeClient(), "local_dev")
            payload = json.loads(credit.credit_summary(task_id="ignored"))
        finally:
            credit.build_platform_client = original_build

        self.assertEqual(paths, ["/hapi/v1/computers/local-dev/credit/v1"])
        self.assertEqual(payload["recent_transactions"], [])

    def test_returns_value_blind_error_when_platform_is_unavailable(self) -> None:
        original_build = credit.build_platform_client
        try:
            def fail() -> tuple[object, str]:
                raise PlatformError("credit route unavailable", status_code=503)

            credit.build_platform_client = fail
            payload = json.loads(credit.credit_summary())
        finally:
            credit.build_platform_client = original_build

        self.assertEqual(payload["schema"], "tinyhat_tool_error_v1")
        self.assertEqual(payload["error"], "credit_summary_unavailable")


if __name__ == "__main__":
    unittest.main()
