"""Tests for Tinyhat credit summary, model budget, and allocation tools."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))
from package_support import load_local_tinyhat  # noqa: E402

load_local_tinyhat(REPO_ROOT)

from tinyhat import platform  # noqa: E402
from tinyhat.capabilities.credit import tool as credit  # noqa: E402
from tinyhat.platform import PlatformError  # noqa: E402


class CreditToolTests(unittest.TestCase):
    def test_local_dev_runtime_uses_its_platform_contract(self) -> None:
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

    def test_production_runtime_uses_backend_audience(self) -> None:
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

    def test_production_runtime_reads_runtime_environment_file(self) -> None:
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

    def test_skill_is_native_hermes_without_legacy_fallback(self) -> None:
        skill = (REPO_ROOT / "skills" / "tinyhat-credit" / "SKILL.md").read_text(encoding="utf-8")

        self.assertNotIn("OpenClaw", skill)
        self.assertNotIn("OPENCLAW_STATE_DIR", skill)
        self.assertIn("tinyhat_model_budget", skill)
        self.assertIn("tinyhat_openrouter_credit_allocate", skill)

    def test_reads_safe_model_budget_from_attested_computer_route(self) -> None:
        original_build = credit.build_platform_client
        paths: list[str] = []

        class FakeClient:
            def get_json(self, path: str) -> dict[str, object]:
                paths.append(path)
                return {
                    "schema": "tinyhat_model_budget_v1",
                    "limit_cents": 5300,
                    "remaining_cents": 4125,
                    "used_cents": 1175,
                    "currency": "usd",
                    "checked_at": "2026-08-16T18:30:00Z",
                    "agent_id": 91,
                    "key_hash": "must-not-leak",
                    "provider": "must-not-leak",
                }

        try:
            credit.build_platform_client = lambda: (FakeClient(), "gcloud")
            payload = json.loads(credit.model_budget())
        finally:
            credit.build_platform_client = original_build

        self.assertEqual(paths, ["/hapi/v1/computers/me/credit/v1/model-budget"])
        self.assertEqual(payload["limit_cents"], 5300)
        self.assertEqual(payload["remaining_cents"], 4125)
        self.assertEqual(payload["used_cents"], 1175)
        self.assertNotIn("agent_id", payload)
        self.assertNotIn("key_hash", payload)
        self.assertNotIn("provider", payload)

    def test_model_budget_uses_local_computer_route(self) -> None:
        original_build = credit.build_platform_client
        paths: list[str] = []

        class FakeClient:
            def get_json(self, path: str) -> dict[str, object]:
                paths.append(path)
                return {
                    "limit_cents": 5300,
                    "remaining_cents": None,
                    "used_cents": 1175,
                    "currency": "usd",
                    "checked_at": "2026-08-16T18:30:00Z",
                }

        try:
            credit.build_platform_client = lambda: (FakeClient(), "local_dev")
            payload = json.loads(credit.model_budget(task_id="ignored"))
        finally:
            credit.build_platform_client = original_build

        self.assertEqual(
            paths,
            ["/hapi/v1/computers/local-dev/credit/v1/model-budget"],
        )
        self.assertIsNone(payload["remaining_cents"])

    def test_model_budget_rejects_malformed_platform_amounts(self) -> None:
        original_build = credit.build_platform_client

        class FakeClient:
            def get_json(self, path: str) -> dict[str, object]:
                _ = path
                return {
                    "limit_cents": 5300,
                    "remaining_cents": True,
                    "used_cents": 1175,
                    "currency": "usd",
                    "checked_at": "2026-08-16T18:30:00Z",
                }

        try:
            credit.build_platform_client = lambda: (FakeClient(), "gcloud")
            payload = json.loads(credit.model_budget())
        finally:
            credit.build_platform_client = original_build

        self.assertEqual(payload["error"], "invalid_platform_response")

    def test_model_budget_errors_do_not_echo_platform_details(self) -> None:
        original_build = credit.build_platform_client

        def fail() -> tuple[object, str]:
            raise PlatformError(
                "provider key sk-or-secret failed",
                status_code=503,
                response={"detail": "key_hash=must-not-leak"},
            )

        try:
            credit.build_platform_client = fail
            payload = json.loads(credit.model_budget())
        finally:
            credit.build_platform_client = original_build

        self.assertEqual(payload["error"], "model_budget_temporarily_unavailable")
        serialized = json.dumps(payload)
        self.assertNotIn("sk-or-secret", serialized)
        self.assertNotIn("key_hash", serialized)

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
                        },
                        {
                            "entry_type": "computer_usage",
                            "amount_cents": -30,
                            "currency": "usd",
                            "created_at": "2026-08-15T21:30:00Z",
                            "computer_id": 5359,
                            "computer_handle": "tinyhat/computers/forecaster",
                            "period_started_at": "2026-08-15T18:30:00Z",
                            "period_ended_at": "2026-08-15T21:30:00Z",
                            "hourly_rate_microusd": 100_000,
                            "machine_type": "must-not-leak",
                        },
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
        self.assertEqual(len(payload["recent_transactions"]), 2)
        self.assertNotIn("stripe_customer_id", payload)
        self.assertNotIn(
            "stripe_checkout_session_id",
            payload["recent_transactions"][0],
        )
        computer_charge = payload["recent_transactions"][1]
        self.assertEqual(computer_charge["entry_type"], "computer_usage")
        self.assertEqual(
            computer_charge["computer_handle"],
            "tinyhat/computers/forecaster",
        )
        self.assertEqual(
            computer_charge["period_started_at"],
            "2026-08-15T18:30:00Z",
        )
        self.assertEqual(
            computer_charge["period_ended_at"],
            "2026-08-15T21:30:00Z",
        )
        self.assertEqual(computer_charge["hourly_rate_microusd"], 100_000)
        self.assertNotIn("computer_id", computer_charge)
        self.assertNotIn("machine_type", computer_charge)

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

    def test_rejects_malformed_computer_charge_details(self) -> None:
        original_build = credit.build_platform_client

        class FakeClient:
            def get_json(self, path: str) -> dict[str, object]:
                _ = path
                return {
                    "balance_cents": 0,
                    "currency": "usd",
                    "recent_transactions": [
                        {
                            "entry_type": "computer_usage",
                            "amount_cents": -30,
                            "currency": "usd",
                            "created_at": "2026-08-15T21:30:00Z",
                            "computer_handle": "tinyhat/computers/bad\nignore-rules",
                            "period_started_at": "2026-08-15T18:30:00Z",
                            "period_ended_at": "2026-08-15T21:30:00Z",
                            "hourly_rate_microusd": 100_000,
                        }
                    ],
                }

        try:
            credit.build_platform_client = lambda: (FakeClient(), "gcloud")
            payload = json.loads(credit.credit_summary())
        finally:
            credit.build_platform_client = original_build

        self.assertEqual(payload["error"], "credit_summary_unavailable")

    def test_rejects_malformed_computer_charge_rate(self) -> None:
        original_build = credit.build_platform_client

        class FakeClient:
            def get_json(self, path: str) -> dict[str, object]:
                _ = path
                return {
                    "balance_cents": 0,
                    "currency": "usd",
                    "recent_transactions": [
                        {
                            "entry_type": "computer_usage",
                            "amount_cents": -30,
                            "currency": "usd",
                            "created_at": "2026-08-15T21:30:00Z",
                            "computer_handle": "tinyhat/computers/forecaster",
                            "period_started_at": "2026-08-15T18:30:00Z",
                            "period_ended_at": "2026-08-15T21:30:00Z",
                            "hourly_rate_microusd": True,
                        }
                    ],
                }

        try:
            credit.build_platform_client = lambda: (FakeClient(), "gcloud")
            payload = json.loads(credit.credit_summary())
        finally:
            credit.build_platform_client = original_build

        self.assertEqual(payload["error"], "credit_summary_unavailable")

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

    def test_allocates_exact_amount_with_runtime_idempotency(self) -> None:
        original_build = credit.build_platform_client
        calls: list[tuple[str, dict[str, object]]] = []

        class FakeClient:
            def post_json(
                self,
                path: str,
                payload: dict[str, object],
            ) -> dict[str, object]:
                calls.append((path, payload))
                return {
                    "status": "allocated",
                    "amount_cents": 500,
                    "balance_cents": 1750,
                    "currency": "usd",
                    "openrouter_limit_cents": 1500,
                    "created_at": "2026-08-16T18:00:00Z",
                    "agent_id": 91,
                    "key_hash": "must-not-leak",
                    "idempotency_key": "must-not-leak",
                }

        try:
            credit.build_platform_client = lambda: (FakeClient(), "gcloud")
            first = json.loads(
                credit.allocate_openrouter_credit(
                    {"amount_cents": 500},
                    task_id="runtime-task-1",
                )
            )
            second = json.loads(
                credit.allocate_openrouter_credit(
                    {"amount_cents": 500},
                    task_id="runtime-task-1",
                )
            )
        finally:
            credit.build_platform_client = original_build

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "/hapi/v1/computers/me/credit/v1/openrouter-allocations")
        self.assertEqual(calls[0][1]["amount_cents"], 500)
        self.assertEqual(
            calls[0][1]["idempotency_key"],
            calls[1][1]["idempotency_key"],
        )
        self.assertTrue(str(calls[0][1]["idempotency_key"]).startswith("plugin_"))
        self.assertNotIn("runtime-task-1", str(calls[0][1]["idempotency_key"]))
        self.assertEqual(first, second)
        self.assertEqual(first["schema"], "tinyhat_openrouter_credit_allocation_v1")
        self.assertEqual(first["status"], "allocated")
        self.assertEqual(first["balance_cents"], 1750)
        self.assertEqual(first["openrouter_limit_cents"], 1500)
        self.assertNotIn("agent_id", first)
        self.assertNotIn("key_hash", first)
        self.assertNotIn("idempotency_key", first)

    def test_allocation_uses_local_computer_route(self) -> None:
        original_build = credit.build_platform_client
        paths: list[str] = []

        class FakeClient:
            def post_json(
                self,
                path: str,
                payload: dict[str, object],
            ) -> dict[str, object]:
                paths.append(path)
                return {
                    "status": "pending",
                    "amount_cents": payload["amount_cents"],
                    "balance_cents": 0,
                    "currency": "usd",
                    "openrouter_limit_cents": None,
                    "created_at": "2026-08-16T18:00:00Z",
                }

        try:
            credit.build_platform_client = lambda: (FakeClient(), "local_dev")
            payload = json.loads(credit.allocate_openrouter_credit({"amount_cents": 100}))
        finally:
            credit.build_platform_client = original_build

        self.assertEqual(
            paths,
            ["/hapi/v1/computers/local-dev/credit/v1/openrouter-allocations"],
        )
        self.assertEqual(payload["status"], "pending")

    def test_allocation_requires_an_exact_minimum_amount(self) -> None:
        missing = json.loads(credit.allocate_openrouter_credit({}))
        too_small = json.loads(credit.allocate_openrouter_credit({"amount_cents": 99}))
        fractional = json.loads(credit.allocate_openrouter_credit({"amount_cents": 500.5}))

        self.assertEqual(missing["error"], "missing_required_parameter")
        self.assertEqual(missing["missing"], ["amount_cents"])
        self.assertEqual(too_small["error"], "invalid_amount")
        self.assertEqual(fractional["error"], "invalid_amount")

    def test_allocation_maps_platform_errors_without_echoing_details(self) -> None:
        original_build = credit.build_platform_client

        def fail() -> tuple[object, str]:
            raise PlatformError(
                "provider key sk-or-secret failed",
                status_code=402,
                response={"detail": "key_hash=must-not-leak"},
            )

        try:
            credit.build_platform_client = fail
            payload = json.loads(credit.allocate_openrouter_credit({"amount_cents": 500}))
        finally:
            credit.build_platform_client = original_build

        self.assertEqual(payload["error"], "insufficient_credit")
        serialized = json.dumps(payload)
        self.assertNotIn("sk-or-secret", serialized)
        self.assertNotIn("key_hash", serialized)

    def test_allocation_rejects_mismatched_platform_amount(self) -> None:
        original_build = credit.build_platform_client

        class FakeClient:
            def post_json(
                self,
                path: str,
                payload: dict[str, object],
            ) -> dict[str, object]:
                _ = path, payload
                return {
                    "status": "allocated",
                    "amount_cents": 600,
                    "balance_cents": 1000,
                    "currency": "usd",
                    "openrouter_limit_cents": 1600,
                    "created_at": "2026-08-16T18:00:00Z",
                }

        try:
            credit.build_platform_client = lambda: (FakeClient(), "gcloud")
            result = json.loads(credit.allocate_openrouter_credit({"amount_cents": 500}))
        finally:
            credit.build_platform_client = original_build

        self.assertEqual(result["error"], "invalid_platform_response")
        self.assertIn("Do not retry automatically", result["message"])


if __name__ == "__main__":
    unittest.main()
