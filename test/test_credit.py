"""Tests for the read-only Tinyhat credit tool."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))

from tinyhat import credit  # noqa: E402
from tinyhat.platform import PlatformError  # noqa: E402


class CreditToolTests(unittest.TestCase):
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
