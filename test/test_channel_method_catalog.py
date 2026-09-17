"""The provider catalog must not bypass destination and message ownership."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("channel_catalog_validator", ROOT / "scripts/validate_framework_package.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class ChannelCatalogTests(unittest.TestCase):
    def test_receipt_policy_is_packaged_as_a_boolean_default(self):
        policy = json.loads((ROOT / "skills/tinyhat-respond/receipt.json").read_text())
        self.assertEqual(set(policy), {"enabled"})
        self.assertIs(type(policy["enabled"]), bool)
        package = json.loads((ROOT / "package.json").read_text())
        self.assertIn("skills", package["files"])

    def test_current_catalog_is_valid(self):
        validator.validate_channel_methods(ROOT)

    def test_invalid_scope_entries_fail_closed(self):
        catalog = json.loads((ROOT / "capabilities/channels/methods.json").read_text())
        for provider, method, rule in (
            ("telegram", "sendMessage", {}),
            ("telegram", "sendMessage", {"target": "recipient"}),
            ("telegram", "editMessageText", {"target": "chat_id", "message": "wrong"}),
            ("slack", "chat.update", {"target": "channel", "typo": "ts"}),
            ("slack", "chat.postMessage", {"target": "channel", "draft": "draft_id"}),
            ("slack", "agents.sessions.setStatus", {"target": "channel_id", "thread_status": "yes"}),
            ("email", "send", {"target": "to"}),
        ):
            with self.subTest(provider=provider, method=method, rule=rule), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "capabilities/channels/methods.json"
                path.parent.mkdir(parents=True)
                modified = copy.deepcopy(catalog)
                modified[provider][method] = rule
                path.write_text(json.dumps(modified))
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    validator.validate_channel_methods(root)
