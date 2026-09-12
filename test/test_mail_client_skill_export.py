"""Run the documented export command and prove its transcript stays value-blind."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class MailClientSkillExportTests(unittest.TestCase):
    def run_export(self, platform_source, *, unsafe=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        package = root / "package"
        package.mkdir()
        private_home = root / "private-home"
        private_home.mkdir()
        if unsafe:
            (private_home / ".config").symlink_to(package, target_is_directory=True)
        (package / "platform.py").write_text(platform_source)
        skill = (Path(__file__).resolve().parents[1] / "skills/tinyhat-mail-client/SKILL.md").read_text()
        code = re.search(r"python - <<'PYTHON'\n(.*?)\nPYTHON", skill, re.S).group(1)
        prefix = "from pathlib import Path\nPath.home = classmethod(lambda cls: Path(" + repr(str(private_home)) + "))\n"
        result = subprocess.run([sys.executable, "-c", prefix + code], cwd=package,
                                text=True, capture_output=True, timeout=15)
        return private_home, package, result

    def test_private_file_receives_values_without_transcript_disclosure(self):
        private_home, package, result = self.run_export('''class Client:
    def post_json(self, path, payload):
        assert path == "/hapi/v2/computers/me/email/client-credentials"
        assert payload == {}
        return {"password": "never-print-password", "smtp_enabled": True,
                "username": "never-print-username", "smtp_host": "never-print-host"}
def build_platform_client():
    return Client(), "gcloud"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("never-print", result.stdout + result.stderr)
        files = list((private_home / ".config/tinyhat/mail-client").glob("settings-*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(files[0].parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads(files[0].read_text())["password"], "never-print-password")
        self.assertEqual(list(package.glob("*.json")), [])

    def test_provider_error_never_enters_transcript(self):
        private_home, _, result = self.run_export('''def build_platform_client():
    raise ValueError("never-print-password")
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("never-print-password", result.stdout + result.stderr)
        self.assertEqual(list(private_home.rglob("settings-*.json")), [])

    def test_symlink_cannot_send_export_into_repository(self):
        _, package, result = self.run_export('''class Client:
    def post_json(self, path, payload):
        return {"password": "never-print-password"}
def build_platform_client():
    return Client(), "gcloud"
''', unsafe=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("never-print-password", result.stdout + result.stderr)
        self.assertEqual(list(package.rglob("settings-*.json")), [])
