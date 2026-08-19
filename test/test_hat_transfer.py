"""Tests for automatic creator-side Hat credential transfer."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))
from package_support import load_local_tinyhat  # noqa: E402

load_local_tinyhat(REPO_ROOT)

from tinyhat.capabilities.hats import transfer as hat_transfer  # noqa: E402


class HatTransferTests(unittest.TestCase):
    def test_runtime_transfer_submits_envelope_and_returns_only_safe_metadata(
        self,
    ) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.posts: list[tuple[str, dict]] = []

            def get_json(self, path: str) -> dict:
                self.path = path
                return {
                    "items": [
                        {
                            "handoff_id": "sh_install_12345678",
                            "installation_id": "hti_install_12345678",
                            "hat_handle": "acme/hats/research",
                            "public_key_pem": "CONSUMER PUBLIC KEY",
                            "consumer_public_key_fingerprint_sha256": "a" * 64,
                            "creator_public_key_fingerprint_sha256": "b" * 64,
                            "credentials": [{"name": "EXA_API_KEY"}],
                        }
                    ]
                }

            def post_json(self, path: str, payload: dict) -> dict:
                self.posts.append((path, payload))
                return {"status": "submitted"}

        client = FakeClient()
        envelope = {
            "schema": "tinyhat_hat_credentials_envelope_v1",
            "ciphertext_chunks_b64": ["ciphertext-only"],
        }
        with (
            mock.patch.object(
                hat_transfer,
                "build_platform_client",
                return_value=(client, "local-dev"),
            ),
            mock.patch.object(
                hat_transfer,
                "create_authenticated_hat_secret_envelope",
                return_value=envelope,
            ) as create_envelope,
        ):
            result = hat_transfer.complete_hat_credential_transfer(
                "sh_install_12345678",
                expected_hat_handle="acme/hats/research",
            )

        create_envelope.assert_called_once_with(
            "acme/hats/research",
            consumer_public_key_pem="CONSUMER PUBLIC KEY",
            expected_names=["EXA_API_KEY"],
            context={
                "handoff_id": "sh_install_12345678",
                "installation_id": "hti_install_12345678",
                "hat_handle": "acme/hats/research",
                "credential_names_sha256": (
                    hat_transfer.credential_names_fingerprint_sha256(["EXA_API_KEY"])
                ),
                "consumer_public_key_fingerprint_sha256": "a" * 64,
            },
            expected_creator_public_key_fingerprint_sha256="b" * 64,
        )
        self.assertEqual(
            client.posts,
            [
                (
                    "/hapi/v1/computers/local-dev/hats/v1/credential-transfers/sh_install_12345678",
                    {"ciphertext_payload": envelope},
                )
            ],
        )
        self.assertEqual(
            result,
            {
                "schema": "tinyhat_hat_credential_transfer_result_v1",
                "handoff_id": "sh_install_12345678",
                "hat_handle": "acme/hats/research",
                "credential_count": 1,
                "submitted": True,
                "authenticated_envelope": True,
                "value_available": False,
            },
        )
        serialized = json.dumps(result)
        self.assertNotIn("ciphertext", serialized)
        self.assertNotIn("PUBLIC KEY", serialized)

    def test_runtime_transfer_rejects_a_different_hat(self) -> None:
        class FakeClient:
            def get_json(self, _path: str) -> dict:
                return {
                    "items": [
                        {
                            "handoff_id": "sh_install_12345678",
                            "hat_handle": "acme/hats/other",
                            "credentials": [{"name": "EXA_API_KEY"}],
                        }
                    ]
                }

        with mock.patch.object(
            hat_transfer,
            "build_platform_client",
            return_value=(FakeClient(), "local-dev"),
        ):
            with self.assertRaisesRegex(Exception, "different Hat"):
                hat_transfer.complete_hat_credential_transfer(
                    "sh_install_12345678",
                    expected_hat_handle="acme/hats/research",
                )


if __name__ == "__main__":
    unittest.main()
