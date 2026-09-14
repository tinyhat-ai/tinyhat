"""Encrypted Computer channel setup and safe tool failures."""

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
load_local_tinyhat = importlib.import_module("package_support").load_local_tinyhat

load_local_tinyhat(ROOT)
runtime = importlib.import_module("tinyhat.capabilities.channels.runtime")
tool = importlib.import_module("tinyhat.capabilities.channels.tool")
_decrypt_ciphertext = importlib.import_module("tinyhat.capabilities.secrets.handoff")._decrypt_ciphertext


class ChannelTests(unittest.TestCase):
    def test_key_survives_retry_and_roundtrip_uses_only_computer_private_key(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}),
        ):
            key = runtime.prepare_key("owner:computer:assignment")
            self.assertEqual(key, runtime.prepare_key("owner:computer:assignment"))
            private = runtime._directory("owner:computer:assignment") / "private.pem"
            self.assertEqual(private.stat().st_mode & 0o777, 0o600)
            bundle = {
                "bot_token": "xoxb-disposable-test",
                "app_token": "xapp-disposable-test",
                "allowed_users": "U12345678",
            }
            envelope = tool.encrypt_bundle(key["public_key_pem"], bundle)
            self.assertNotIn(bundle["bot_token"], json.dumps(envelope))
            self.assertEqual(json.loads(_decrypt_ciphertext(private.read_text(), envelope)), bundle)
            other = runtime.prepare_key("different-assignment")
            self.assertNotEqual(other["key_fingerprint"], key["key_fingerprint"])
            (private.parent / "public.pem").unlink()
            self.assertEqual(runtime.prepare_key("owner:computer:assignment"), key)

    def test_private_file_accepts_plain_bundle_but_rejects_shared_or_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "slack.json"
            path.write_text(
                json.dumps(
                    {
                        "bot_token": "xoxb-disposable-test",
                        "app_token": "xapp-disposable-test",
                        "allowed_users": "U12345678",
                    }
                )
            )
            path.chmod(0o600)
            self.assertEqual(tool._credentials_file(str(path))["allowed_users"], "U12345678")
            link = Path(directory) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                tool._credentials_file(str(link))
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                tool._credentials_file(str(path))

    def test_slack_only_sets_slack_keys_after_matching_app_identity(self):
        bundle = {
            "bot_token": "xoxb-disposable-test",
            "app_token": "xapp-1-A12345678-test",
            "allowed_users": "U12345678",
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}),
        ):
            key = runtime.prepare_key("assignment")
            envelope = tool.encrypt_bundle(
                key["public_key_pem"], {"schema": "tinyhat_slack_connection_bundle_v1", **bundle}
            )
            channel = {
                "provider": "slack",
                "key_fingerprint": key["key_fingerprint"],
                "ciphertext": envelope,
            }
            with (
                patch.object(
                    runtime,
                    "_validate_slack_credentials",
                    return_value={"workspace_id": "T12345678"},
                ),
                patch.object(runtime, "_open_slack_home_channel", return_value="D12345678"),
                patch.object(
                    runtime,
                    "_slack_api_call",
                    side_effect=[{"bot_id": "B12345678"}, {"bot": {"app_id": "A12345678"}}],
                ),
                patch.object(runtime, "_set_hermes_secret") as save,
            ):
                runtime.install_channel("assignment", channel)
                self.assertEqual(
                    {call.args[0] for call in save.call_args_list},
                    {
                        "SLACK_BOT_TOKEN",
                        "SLACK_APP_TOKEN",
                        "SLACK_ALLOWED_USERS",
                        "SLACK_HOME_CHANNEL",
                        "SLACK_HOME_CHANNEL_NAME",
                    },
                )
            with (
                patch.object(runtime, "_validate_slack_credentials", return_value={}),
                patch.object(
                    runtime,
                    "_slack_api_call",
                    side_effect=[{"bot_id": "B12345678"}, {"bot": {"app_id": "A99999999"}}],
                ),
                patch.object(runtime, "_set_hermes_secret") as save,
            ):
                with self.assertRaises(ValueError):
                    runtime.install_channel("assignment", channel)
                save.assert_not_called()

    def test_invalid_credentials_are_not_returned_by_tool(self):
        client = Mock()
        with patch.object(tool, "build_platform_client", return_value=(client, "gcloud")):
            result = tool.channels({"action": "slack_connect", "bot_token": "xoxb-private-value"})
            self.assertNotIn("xoxb-private-value", result)
            self.assertIn("channel_setup_unavailable", result)
            client.get_json.assert_not_called()

    def test_status_uses_nonsecret_route_and_filters_internal_fields(self):
        client = Mock()
        client.get_json.return_value = {
            "channels": [
                {
                    "provider": "slack",
                    "status": "connected",
                    "name": "Workspace",
                    "bot_token": "private-value",
                }
            ],
            "public_key_pem": "public",
            "ciphertext": "private-envelope",
        }
        with patch.object(tool, "build_platform_client", return_value=(client, "gcloud")):
            result = tool.channels()
        client.get_json.assert_called_once_with("/hapi/v2/computers/me/channels/status")
        self.assertNotIn("private-value", result)
        self.assertNotIn("private-envelope", result)


if __name__ == "__main__":
    unittest.main()
