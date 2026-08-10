"""Tests for namespaced, Computer-local Hat skill installation."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT.parent))

from tinyhat import hat_skill_installer  # noqa: E402


class HatSkillInstallerTests(unittest.TestCase):
    def test_installs_namespaced_skills_and_removes_only_stale_hat_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout"
            skills_root = root / "hermes-skills"
            home = root / "home"
            first = checkout / "skills" / "research"
            first.mkdir(parents=True)
            (first / "SKILL.md").write_text("---\nname: research\n---\n", encoding="utf-8")
            unrelated = skills_root / "user-authored"
            unrelated.mkdir(parents=True)
            (unrelated / "SKILL.md").write_text("user", encoding="utf-8")

            with (
                mock.patch.dict(os.environ, {"HERMES_SKILLS_ROOT": str(skills_root)}),
                mock.patch.object(Path, "home", return_value=home),
            ):
                installed = hat_skill_installer.install_hat_skills(
                    "acme/hats/research", str(checkout)
                )
                self.assertEqual(installed["count"], 1)
                target = skills_root / installed["installed_names"][0]
                self.assertTrue((target / "SKILL.md").is_file())

                for child in first.iterdir():
                    child.unlink()
                first.rmdir()
                removed = hat_skill_installer.install_hat_skills(
                    "acme/hats/research", str(checkout)
                )

            self.assertEqual(removed["count"], 0)
            self.assertFalse(target.exists())
            self.assertTrue((unrelated / "SKILL.md").is_file())

    def test_rejects_symlinked_skill_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout"
            skill = checkout / "skills" / "research"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("skill", encoding="utf-8")
            (skill / "secret-link").symlink_to(root / "outside")
            with (
                mock.patch.dict(os.environ, {"HERMES_SKILLS_ROOT": str(root / "skills")}),
                mock.patch.object(Path, "home", return_value=root / "home"),
                self.assertRaises(hat_skill_installer.HatSkillInstallError),
            ):
                hat_skill_installer.install_hat_skills(
                    "acme/hats/research", str(checkout)
                )

    def test_later_copy_failure_preserves_every_active_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout"
            skills_root = root / "hermes-skills"
            home = root / "home"
            for name in ("alpha", "bravo"):
                source = checkout / "skills" / name
                source.mkdir(parents=True)
                (source / "SKILL.md").write_text(
                    f"old-{name}", encoding="utf-8"
                )

            with (
                mock.patch.dict(os.environ, {"HERMES_SKILLS_ROOT": str(skills_root)}),
                mock.patch.object(Path, "home", return_value=home),
            ):
                first = hat_skill_installer.install_hat_skills(
                    "acme/hats/research", str(checkout)
                )
                targets = [skills_root / name for name in first["installed_names"]]
                for name in ("alpha", "bravo"):
                    (checkout / "skills" / name / "SKILL.md").write_text(
                        f"new-{name}", encoding="utf-8"
                    )
                real_copytree = hat_skill_installer.shutil.copytree
                copy_count = 0

                def fail_second_copy(source: Path, target: Path) -> Path:
                    nonlocal copy_count
                    copy_count += 1
                    if copy_count == 2:
                        raise OSError("simulated second-package copy failure")
                    return real_copytree(source, target)

                with (
                    mock.patch.object(
                        hat_skill_installer.shutil,
                        "copytree",
                        side_effect=fail_second_copy,
                    ),
                    self.assertRaises(OSError),
                ):
                    hat_skill_installer.install_hat_skills(
                        "acme/hats/research", str(checkout)
                    )

            self.assertEqual(
                sorted(
                    target.joinpath("SKILL.md").read_text(encoding="utf-8")
                    for target in targets
                ),
                ["old-alpha", "old-bravo"],
            )


if __name__ == "__main__":
    unittest.main()
