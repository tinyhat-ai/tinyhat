"""Tests for the plugin-to-runtime Hat repository bridge."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))

from tinyhat import hat_repository


class HatRepositoryBridgeTests(unittest.TestCase):
    @staticmethod
    def _checkout_result() -> dict[str, object]:
        return {
            "schema": "tinyhat_hat_repository_v1",
            "action": "checkout",
            "hat_handle": "acme/hats/demo",
            "repository": {"owner": "tinyhat-ai", "name": "demo"},
            "path": "/home/agent/.hermes/hat-repositories/acme/demo",
            "branch": "main",
            "head_sha": "a" * 40,
            "created": True,
            "credential_persisted": False,
        }

    def test_passes_payload_on_stdin_and_returns_safe_runtime_result(self) -> None:
        runtime_result = self._checkout_result()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(runtime_result),
            stderr="",
        )
        with mock.patch.object(
            hat_repository.subprocess,
            "run",
            return_value=completed,
        ) as run:
            result = hat_repository.run_hat_repository(
                {"action": "checkout", "identifier": "acme/hats/demo"}
            )

        self.assertEqual(result, runtime_result)
        self.assertEqual(
            json.loads(run.call_args.kwargs["input"]),
            {"action": "checkout", "identifier": "acme/hats/demo"},
        )
        self.assertEqual(
            run.call_args.args[0],
            [sys.executable, "-m", "hermes_runtime.hat_repository_cli"],
        )

    def test_rejects_credential_shaped_runtime_output(self) -> None:
        unsafe_keys = (
            "token",
            "access_token",
            "accessTOKEN",
            "lease-token",
            "refreshToken",
            "clientSecret",
            "authorization",
            "private_key",
            "privateKey",
            "signingPrivateKey",
            "api_key",
            "apiKey",
            "APIKey",
            "credentials",
            "credential_value",
            "githubCredential",
            "auth",
            "bearer",
        )
        for unsafe_key in unsafe_keys:
            with self.subTest(unsafe_key=unsafe_key):
                runtime_result = self._checkout_result()
                runtime_result["repository"] = {
                    "owner": "tinyhat-ai",
                    "name": "demo",
                    unsafe_key: "unexpected",
                }
                self._assert_runtime_output_rejected(runtime_result)

    def test_allows_safe_credential_state_metadata(self) -> None:
        runtime_result = self._checkout_result()
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(runtime_result),
            stderr="",
        )
        with mock.patch.object(
            hat_repository.subprocess,
            "run",
            return_value=completed,
        ):
            self.assertEqual(
                hat_repository.run_hat_repository(
                    {"action": "checkout", "identifier": "demo"}
                ),
                runtime_result,
            )

    def test_rejects_unknown_or_wrongly_typed_runtime_fields(self) -> None:
        unknown = self._checkout_result()
        unknown["session_id"] = "unexpected"
        self._assert_runtime_output_rejected(unknown)

        nested = self._checkout_result()
        nested["repository"] = {
            "owner": "tinyhat-ai",
            "name": "demo",
            "metadata": {"githubCredential": "unexpected"},
        }
        self._assert_runtime_output_rejected(nested)

        wrong_type = self._checkout_result()
        wrong_type["created"] = "yes"
        self._assert_runtime_output_rejected(wrong_type)

    def test_rejects_result_for_a_different_requested_action(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(self._checkout_result()),
            stderr="",
        )
        with mock.patch.object(
            hat_repository.subprocess,
            "run",
            return_value=completed,
        ):
            with self.assertRaises(hat_repository.HatRepositoryRuntimeError):
                hat_repository.run_hat_repository(
                    {"action": "reset", "identifier": "demo"}
                )

    def _assert_runtime_output_rejected(self, output: object) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(output),
            stderr="",
        )
        with mock.patch.object(
            hat_repository.subprocess,
            "run",
            return_value=completed,
        ):
            with self.assertRaises(hat_repository.HatRepositoryRuntimeError):
                hat_repository.run_hat_repository(
                    {"action": "checkout", "identifier": "demo"}
                )


if __name__ == "__main__":
    unittest.main()
