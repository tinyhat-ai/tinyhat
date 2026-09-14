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
_decrypt_ciphertext = importlib.import_module(
    "tinyhat.capabilities.secrets.handoff"
)._decrypt_ciphertext


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

    def test_partial_key_recovers_only_before_publication(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}),
        ):
            folder = runtime._directory("partial")
            private = folder / "private.pem"
            private.write_text("")
            key = runtime.prepare_key("partial")
            self.assertTrue(key["public_key_pem"].startswith("-----BEGIN PUBLIC KEY"))
            private.unlink()
            with self.assertRaises(ValueError):
                runtime.prepare_key("partial")

    def test_telegram_validates_owner_and_writes_allowlist_first(self):
        channel = {
            "provider": "telegram",
            "bot_token": "12345:" + "a" * 35,
            "owner_id": "12345",
            "settings_miniapp_url": "https://example.com/computer",
        }
        with patch.object(runtime, "_set_hermes_secret") as save:
            runtime.install_channel("assignment", channel)
            self.assertEqual(
                [c.args[0] for c in save.call_args_list],
                [
                    "TELEGRAM_ALLOWED_USERS",
                    "TELEGRAM_HOME_CHANNEL",
                    "TELEGRAM_HOME_CHANNEL_NAME",
                    "TINYHAT_SETTINGS_MINIAPP_URL",
                    "TELEGRAM_BOT_TOKEN",
                ],
            )
            save.reset_mock()
            for owner in ["0", "-1", "not-an-id"]:
                with self.assertRaises(ValueError):
                    runtime.install_channel("assignment", {**channel, "owner_id": owner})
            save.assert_not_called()

    def test_snapshot_uses_hermes_values_and_aborts_on_loader_failure(self):
        snapshot = dict.fromkeys(runtime.CHANNEL_KEYS["telegram"])
        snapshot["TELEGRAM_BOT_TOKEN"] = "previous"
        with (
            patch.object(runtime.shutil, "which", return_value="hermes"),
            patch.object(runtime, "_hermes_python_executable", return_value="hermes-python"),
            patch.object(
                runtime.subprocess,
                "run",
                return_value=Mock(returncode=0, stdout=json.dumps(snapshot)),
            ) as load,
            patch.object(runtime, "_set_hermes_secret") as save,
        ):
            self.assertEqual(runtime.snapshot_channel("telegram"), snapshot)
            self.assertEqual(load.call_args.args[0][0], "hermes-python")
            for result in [
                Mock(returncode=1, stdout=""),
                Mock(returncode=0, stdout="invalid"),
                Mock(returncode=0, stdout="{}"),
            ]:
                load.return_value = result
                with self.assertRaises(ValueError):
                    runtime.snapshot_channel("telegram")
            save.assert_not_called()
            runtime.restore_channel(snapshot)
            self.assertEqual(save.call_args_list[-1].args, ("TELEGRAM_BOT_TOKEN", "previous"))
            save.reset_mock()
            for invalid in [
                {**snapshot, "OTHER_VALUE": "never-write"},
                {**snapshot, "TELEGRAM_BOT_TOKEN": 3},
            ]:
                with self.assertRaises(ValueError):
                    runtime.restore_channel(invalid)
                save.assert_not_called()

    def test_corrupt_unpublished_key_recovers_but_published_key_is_preserved(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}),
        ):
            folder = runtime._directory("corrupt")
            private = folder / "private.pem"
            private.write_text("interrupted-write")
            key = runtime.prepare_key("corrupt")
            self.assertTrue(key["public_key_pem"].startswith("-----BEGIN PUBLIC KEY"))
            private.write_text("corrupt-published")
            self.assertEqual(runtime.prepare_key("corrupt"), key)
            self.assertEqual(private.read_text(), "corrupt-published")

    def test_nonzero_openssl_does_not_delete_a_nonempty_private_key(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}),
        ):
            private = runtime._directory("unpublished") / "private.pem"
            private.write_text(
                "-----BEGIN PRIVATE KEY-----\npossibly-valid-but-unreadable-to-openssl"
            )
            with (
                patch.object(runtime.subprocess, "run", return_value=Mock(returncode=1)),
                self.assertRaises(ValueError),
            ):
                runtime.prepare_key("unpublished")
            self.assertTrue(private.exists())

    def test_telegram_missing_settings_never_blanks_existing_values(self):
        with patch.object(runtime, "_set_hermes_secret") as save:
            with self.assertRaises(ValueError):
                runtime.install_channel(
                    "assignment",
                    {"provider": "telegram", "bot_token": "12345:" + "a" * 35, "owner_id": "12345"},
                )
            save.assert_not_called()

    def test_pairing_urls_share_origin_token_and_safe_transport(self):
        token = "thch_" + "a" * 43

        def payload(origin):
            return {
                "url": origin + "/tinyhat/connect/telegram/" + token,
                "qr_url": origin + "/hapi/v2/channel-links/telegram/" + token + "/qr",
            }

        for origin in ["https://example.com", "http://localhost:8012"]:
            self.assertEqual(tool.pairing_result(payload(origin))["url"], payload(origin)["url"])
        for bad in [
            {**payload("https://example.com"), "qr_url": "https://other.example/qr"},
            payload("http://example.com"),
        ]:
            with self.assertRaises(tool.ChannelInputError):
                tool.pairing_result(bad)

    def test_not_prepared_and_platform_errors_are_actionable_without_secrets(self):
        client = Mock()
        client.get_json.return_value = {}
        with patch.object(tool, "build_platform_client", return_value=(client, "local_dev")):
            self.assertIn("computer_not_prepared", tool.channels({"action": "slack_connect"}))
            client.get_json.side_effect = tool.PlatformError("secret-token", status_code=503)
            result = tool.channels()
            self.assertIn("platform_unavailable", result)
            self.assertNotIn("secret-token", result)

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
                    [call.args[0] for call in save.call_args_list],
                    [
                        "SLACK_ALLOWED_USERS",
                        "SLACK_HOME_CHANNEL",
                        "SLACK_HOME_CHANNEL_NAME",
                        "SLACK_BOT_TOKEN",
                        "SLACK_APP_TOKEN",
                    ],
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
