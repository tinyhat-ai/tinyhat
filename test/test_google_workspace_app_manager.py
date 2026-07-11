"""Managed Google Workspace app lifecycle tests."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
PARENT = REPO_ROOT.parent
sys.path.insert(0, str(PARENT))

if REPO_ROOT.name != "tinyhat":
    spec = importlib.util.spec_from_file_location(
        "tinyhat",
        REPO_ROOT / "__init__.py",
        submodule_search_locations=[str(REPO_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load local tinyhat package for tests.")
    tinyhat = importlib.util.module_from_spec(spec)
    sys.modules["tinyhat"] = tinyhat
    spec.loader.exec_module(tinyhat)
else:
    import tinyhat  # type: ignore[no-redef]

from tinyhat import google_workspace_app_manager as manager  # noqa: E402
from tinyhat import schemas, tools  # noqa: E402


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def archive_with(entries: list[tuple[str, bytes, str]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as bundle:
        for name, content, kind in entries:
            item = tarfile.TarInfo(name)
            if kind == "file":
                item.size = len(content)
                item.mode = 0o755
                bundle.addfile(item, io.BytesIO(content))
            elif kind == "symlink":
                item.type = tarfile.SYMTYPE
                item.linkname = "../../outside"
                bundle.addfile(item)
            else:
                item.type = tarfile.DIRTYPE
                bundle.addfile(item)
    return output.getvalue()


class GoogleWorkspaceAppManagerTests(unittest.TestCase):
    def test_packaged_shared_skill_matches_hardcoded_hash(self) -> None:
        self.assertEqual(
            sha(manager.TINYHAT_SHARED_SKILL_SOURCE.read_bytes()),
            manager.TINYHAT_SHARED_SKILL_SHA256,
        )

    @contextmanager
    def configured_manager(self):
        binary = b"fake-pinned-gws"
        archive = archive_with([("./gws", binary, "file")])
        official = b"official-calendar-skill"
        shared = b"tinyhat-shared-skill"
        artifact = manager.GwsReleaseArtifact(
            architecture="x86_64",
            archive_url=manager.PINNED_ARCHIVE_URL,
            archive_sha256=sha(archive),
            binary_sha256=sha(binary),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shared_source = root / "package" / "gws-shared" / "SKILL.md"
            shared_source.parent.mkdir(parents=True)
            shared_source.write_bytes(shared)
            install_root = root / "opt" / "tinyhat"
            with ExitStack() as stack:
                stack.enter_context(
                    mock.patch.object(manager, "INSTALL_ROOT", install_root)
                )
                stack.enter_context(
                    mock.patch.object(manager, "BINARY_PATH", install_root / "bin" / "gws")
                )
                stack.enter_context(
                    mock.patch.object(manager, "STATE_DIR", install_root / "state")
                )
                stack.enter_context(
                    mock.patch.object(
                        manager,
                        "MANIFEST_PATH",
                        install_root / "state" / "google-workspace-app.json",
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        manager,
                        "QUARANTINE_DIR",
                        install_root / "quarantine",
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        manager,
                        "HERMES_SKILLS_ROOT",
                        root / "root" / ".hermes" / "skills",
                    )
                )
                stack.enter_context(
                    mock.patch.object(manager, "TINYHAT_SHARED_SKILL_SOURCE", shared_source)
                )
                stack.enter_context(
                    mock.patch.object(manager, "TINYHAT_SHARED_SKILL_SHA256", sha(shared))
                )
                stack.enter_context(
                    mock.patch.object(
                        manager,
                        "PINNED_OFFICIAL_SKILLS",
                        {"gws-calendar": sha(official)},
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        manager,
                        "TRUSTED_MANAGED_RELEASES",
                        {
                            manager.PINNED_GWS_VERSION: {
                                "artifacts": {artifact.architecture: artifact},
                                "skills": {"gws-calendar": sha(official)},
                                "shared_sha256": sha(shared),
                            }
                        },
                    )
                )
                stack.enter_context(
                    mock.patch.object(
                        manager,
                        "_require_supported_host",
                        return_value=artifact,
                    )
                )

                def download(url: str, *, max_bytes: int) -> bytes:
                    _ = max_bytes
                    return archive if url == manager.PINNED_ARCHIVE_URL else official

                stack.enter_context(
                    mock.patch.object(manager, "_download_bytes", side_effect=download)
                )
                yield {
                    "root": root,
                    "archive": archive,
                    "binary": binary,
                    "official": official,
                    "shared": shared,
                }

    def test_schema_and_adapter_expose_manager_without_raw_version_or_url(self) -> None:
        schema = schemas.TINYHAT_GOOGLE_WORKSPACE_APP_MANAGER_SCHEMA
        context = mock.Mock()

        tinyhat.register(context)

        self.assertEqual(set(schema["properties"]), {"action", "confirmed"})
        self.assertEqual(schema["properties"]["action"]["enum"], list(manager.MANAGER_ACTIONS))
        self.assertFalse(schema["additionalProperties"])
        manager_calls = [
            call.kwargs
            for call in context.register_tool.call_args_list
            if call.kwargs.get("name") == "tinyhat_google_workspace_app_manager"
        ]
        self.assertEqual(len(manager_calls), 1)
        self.assertIs(manager_calls[0]["handler"], tools.google_workspace_app_manager)
        self.assertIs(manager_calls[0]["schema"], schema)

    def test_install_and_uninstall_require_separate_confirmation(self) -> None:
        install = json.loads(tools.google_workspace_app_manager({"action": "install"}))
        uninstall = json.loads(tools.google_workspace_app_manager({"action": "uninstall"}))

        self.assertEqual(install["error"], "confirmation_required")
        self.assertEqual(uninstall["error"], "confirmation_required")

    def test_unsupported_platform_fails_before_install(self) -> None:
        unsupported = mock.Mock(sysname="Darwin", machine="arm64")
        with mock.patch.object(manager.os, "uname", return_value=unsupported):
            result = json.loads(tools.google_workspace_app_manager({"action": "status"}))

        self.assertEqual(result["error"], "unsupported_platform")
        self.assertNotIn("/opt/", json.dumps(result))

    def test_linux_x86_and_arm_aliases_select_hardcoded_artifacts(self) -> None:
        cases = {
            "x86_64": "x86_64",
            "amd64": "x86_64",
            "aarch64": "aarch64",
            "arm64": "aarch64",
        }
        for machine, expected in cases.items():
            host = mock.Mock(sysname="Linux", machine=machine)
            with (
                self.subTest(machine=machine),
                mock.patch.object(manager.os, "uname", return_value=host),
                mock.patch.object(manager.os, "geteuid", return_value=0),
                mock.patch.object(
                    manager,
                    "HERMES_SKILLS_ROOT",
                    Path("/root/.hermes/skills"),
                ),
                mock.patch.object(manager, "_validate_trusted_hermes_home"),
                mock.patch.object(manager, "_validate_fixed_install_root"),
            ):
                artifact = manager._require_supported_host()
            self.assertEqual(artifact.architecture, expected)

    def test_archive_hash_mismatch_stops_before_extraction(self) -> None:
        with self.configured_manager():
            bad_artifact = manager.GwsReleaseArtifact(
                architecture="x86_64",
                archive_url=manager.PINNED_ARCHIVE_URL,
                archive_sha256="0" * 64,
                binary_sha256=manager.PINNED_BINARY_SHA256,
            )
            with mock.patch.object(
                manager, "_require_supported_host", return_value=bad_artifact
            ), self.assertRaises(manager.GoogleWorkspaceAppManagerError) as raised:
                manager.install_managed_app()

        self.assertEqual(raised.exception.code, "integrity_mismatch")

    def test_archive_rejects_traversal_and_links(self) -> None:
        variants = [
            archive_with([("../outside", b"bad", "file"), ("gws", b"ok", "file")]),
            archive_with([("gws", b"", "symlink")]),
        ]
        for archive in variants:
            with self.subTest(), self.assertRaises(
                manager.GoogleWorkspaceAppManagerError
            ) as raised:
                manager._extract_gws_binary(archive)
            self.assertEqual(raised.exception.code, "unsafe_archive")

    def test_install_is_transactional_when_second_replace_fails(self) -> None:
        with self.configured_manager():
            real_replace = os.replace
            skill_target = manager.HERMES_SKILLS_ROOT / "gws-calendar" / "SKILL.md"

            def replace(source, target):
                if Path(target) == skill_target and "tinyhat-stage" in Path(source).name:
                    raise OSError("injected commit failure")
                return real_replace(source, target)

            with (
                mock.patch.object(manager.os, "replace", side_effect=replace),
                self.assertRaises(manager.GoogleWorkspaceAppManagerError) as raised,
            ):
                manager.install_managed_app()

            self.assertEqual(raised.exception.code, "install_failed")
            self.assertFalse(manager.BINARY_PATH.exists())
            self.assertFalse(skill_target.exists())
            self.assertFalse(manager.MANIFEST_PATH.exists())

    def test_next_install_recovers_exact_orphan_after_process_kill_window(self) -> None:
        with self.configured_manager():
            real_replace = os.replace
            skill_target = manager.HERMES_SKILLS_ROOT / "gws-calendar" / "SKILL.md"
            interrupted = False

            def replace(source, target):
                nonlocal interrupted
                if (
                    not interrupted
                    and Path(target) == skill_target
                    and "tinyhat-stage" in Path(source).name
                ):
                    interrupted = True
                    raise KeyboardInterrupt("simulated SIGKILL window")
                return real_replace(source, target)

            with (
                mock.patch.object(manager.os, "replace", side_effect=replace),
                self.assertRaises(KeyboardInterrupt),
            ):
                manager.install_managed_app()

            self.assertTrue(manager.BINARY_PATH.exists())
            self.assertFalse(manager.MANIFEST_PATH.exists())

            recovered = manager.install_managed_app()
            status = manager.managed_app_status()

            self.assertEqual(recovered["status"], "installed")
            self.assertEqual(status["status"], "installed")

    def test_status_and_bridge_reject_manifest_that_blesses_replaced_binary(self) -> None:
        with self.configured_manager():
            manager.install_managed_app()
            manager.BINARY_PATH.write_bytes(b"replacement")
            manager.BINARY_PATH.chmod(0o755)
            manifest = json.loads(manager.MANIFEST_PATH.read_text())
            manifest["components"]["gws"]["sha256"] = sha(b"replacement")
            manager.MANIFEST_PATH.write_text(json.dumps(manifest), encoding="utf-8")
            manager.MANIFEST_PATH.chmod(0o600)

            with (
                self.assertRaises(manager.GoogleWorkspaceAppManagerError) as raised,
                manager.verified_managed_gws_binary(),
            ):
                self.fail("tampered manifest must not yield an executable")

        self.assertEqual(raised.exception.code, "managed_state_invalid")

    def test_bridge_rejects_any_modified_operation_or_shared_skill(self) -> None:
        for name in ("gws-calendar", "gws-shared"):
            with self.subTest(name=name), self.configured_manager():
                manager.install_managed_app()
                skill = manager.HERMES_SKILLS_ROOT / name / "SKILL.md"
                skill.write_bytes(b"prompt injection")
                skill.chmod(0o644)

                with (
                    self.assertRaises(manager.GoogleWorkspaceAppManagerError) as raised,
                    manager.verified_managed_gws_binary(),
                ):
                    self.fail("modified skills must block token lending")

                self.assertEqual(raised.exception.code, "app_unavailable")

    def test_uninstall_quarantines_modified_skill_out_of_active_path(self) -> None:
        with self.configured_manager():
            manager.install_managed_app()
            skill = manager.HERMES_SKILLS_ROOT / "gws-calendar" / "SKILL.md"
            skill.write_bytes(b"locally modified")
            skill.chmod(0o644)

            result = manager.uninstall_managed_app()

            self.assertEqual(result["status"], "uninstalled")
            self.assertEqual(result["quarantined_modified_components"], ["skill:gws-calendar"])
            self.assertFalse(skill.exists())
            self.assertFalse(manager.BINARY_PATH.exists())
            self.assertFalse(manager.MANIFEST_PATH.exists())
            quarantined = list(manager.QUARANTINE_DIR.iterdir())
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(quarantined[0].read_bytes(), b"locally modified")
            self.assertEqual(quarantined[0].stat().st_mode & 0o777, 0o600)

    def test_real_manifest_records_are_complete_and_hardcoded(self) -> None:
        with self.configured_manager():
            result = manager.install_managed_app()
            status = manager.managed_app_status()

            self.assertEqual(result["status"], "installed")
            self.assertEqual(status["status"], "installed")
            self.assertTrue(status["binary_ready"])
            self.assertTrue(status["skills_ready"])

    def test_old_trusted_manifest_remains_uninstallable_after_next_pin(self) -> None:
        with self.configured_manager():
            manager.install_managed_app()
            old_release = manager.TRUSTED_MANAGED_RELEASES["0.22.5"]

            with (
                mock.patch.object(manager, "PINNED_GWS_VERSION", "0.22.6"),
                mock.patch.object(
                    manager,
                    "TRUSTED_MANAGED_RELEASES",
                    {"0.22.5": old_release, "0.22.6": old_release},
                ),
            ):
                result = manager.uninstall_managed_app()

            self.assertEqual(result["status"], "uninstalled")
            self.assertFalse(manager.MANIFEST_PATH.exists())

    @unittest.skipUnless(
        hasattr(os, "memfd_create") and hasattr(manager.fcntl, "F_ADD_SEALS"),
        "sealed memfd requires Linux",
    )
    def test_verified_copy_is_sealed_against_post_hash_writes(self) -> None:
        content = b"known executable bytes"
        with tempfile.TemporaryFile() as source:
            source.write(content)
            source.flush()
            sealed_fd = manager._sealed_executable_copy(
                source.fileno(), expected_sha256=sha(content)
            )
            try:
                with self.assertRaises(OSError):
                    os.write(sealed_fd, b"mutation")
            finally:
                os.close(sealed_fd)


if __name__ == "__main__":
    unittest.main()
