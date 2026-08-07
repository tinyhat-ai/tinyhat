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
    def test_passes_payload_on_stdin_and_returns_safe_runtime_result(self) -> None:
        runtime_result = {
            "schema": "tinyhat_hat_repository_v1",
            "action": "checkout",
            "path": "/home/agent/.hermes/hat-repositories/acme/demo",
            "credential_persisted": False,
        }
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
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"action": "checkout", "token": "unexpected"}),
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
