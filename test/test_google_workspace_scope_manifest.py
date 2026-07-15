"""Tests for the public Google Workspace OAuth scope manifest."""

from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import MappingProxyType
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

from tinyhat import google_workspace_scope_manifest as manifest  # noqa: E402

VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "tinyhat_validate_framework_package",
    REPO_ROOT / "scripts" / "validate_framework_package.py",
)
if VALIDATOR_SPEC is None or VALIDATOR_SPEC.loader is None:
    raise RuntimeError("Could not load the framework package validator for tests.")
validator = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(validator)


class GoogleWorkspaceScopeManifestTests(unittest.TestCase):
    def raw_manifest(self) -> dict[str, object]:
        return json.loads(manifest.MANIFEST_PATH.read_text(encoding="utf-8"))

    def load_changed(self, raw: dict[str, object]) -> object:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            return manifest.load_manifest(path)

    def test_manifest_is_strictly_loaded_and_recursively_immutable(self) -> None:
        self.assertEqual(manifest.MANIFEST["schema"], manifest.MANIFEST_SCHEMA)
        self.assertEqual(manifest.MANIFEST["manifest_version"], "1.0.1")
        self.assertEqual(manifest.IDENTITY_BUNDLE_ID, "google_workspace_identity_v1")
        self.assertIsInstance(manifest.MANIFEST, MappingProxyType)
        self.assertIsInstance(manifest.MANIFEST["scopes"], tuple)
        self.assertIsInstance(manifest.MANIFEST["scopes"][0], MappingProxyType)
        with self.assertRaises(TypeError):
            manifest.MANIFEST["manifest_version"] = "2.0.0"  # type: ignore[index]
        with self.assertRaises(TypeError):
            manifest.SCOPES_BY_ID["openid"]["display_name"] = "changed"  # type: ignore[index]

    def test_identity_baseline_is_exact_and_identity_first(self) -> None:
        self.assertEqual(manifest.IDENTITY_SCOPE_IDS, ("openid", "email", "profile"))
        self.assertEqual(manifest.IDENTITY_SCOPE_URLS, ("openid", "email", "profile"))
        resolved = manifest.resolve_scope_request()
        self.assertEqual(resolved.scope_urls, ("openid", "email", "profile"))
        self.assertEqual(resolved.services, ("identity",))
        self.assertEqual(resolved.capabilities, ("account_identity",))
        self.assertEqual(resolved.bundle_id, "google_workspace_identity_v1")
        self.assertEqual(resolved.access_label, "Identity only")
        self.assertTrue(resolved.read_only)
        self.assertTrue(resolved.approved)

    def test_five_presets_have_the_required_exact_scope_membership(self) -> None:
        expected = {
            "workspace_reader": (
                ("gmail.readonly", "calendar.events.readonly", "drive.readonly"),
                "restricted",
            ),
            "mail_writer": (("gmail.compose",), "restricted"),
            "inbox_manager": (("gmail.modify",), "restricted"),
            "calendar_coordinator": (("calendar.events",), "sensitive"),
            "file_collaborator": (("drive.file",), "non_sensitive"),
        }
        self.assertEqual(set(manifest.PRESETS_BY_ID), set(expected))
        for preset_id, (scope_ids, risk_class) in expected.items():
            preset = manifest.PRESETS_BY_ID[preset_id]
            self.assertEqual(tuple(preset["scope_ids"]), scope_ids)
            self.assertEqual(preset["risk_class"], risk_class)
            self.assertIs(preset["recommended"], True)
            self.assertIs(preset["default"], False)

    def test_every_scope_carries_verification_and_data_use_evidence(self) -> None:
        required = {
            "canonical_url",
            "classification",
            "enabled_api",
            "implemented_feature",
            "operations",
            "data_read",
            "data_written",
            "narrower_alternatives",
            "why_narrower_insufficient",
            "user_copy",
            "demo_steps",
            "verification_status",
            "client_states",
        }
        for scope_id, scope in manifest.SCOPES_BY_ID.items():
            with self.subTest(scope_id=scope_id):
                self.assertTrue(required <= set(scope))
                self.assertTrue(scope["why_narrower_insufficient"])
                self.assertEqual(
                    set(scope["client_states"]),
                    {"tinyhat-development", "tinyhat-production"},
                )
                self.assertEqual(scope["read_only"], scope["access_mode"] == "read")

    def test_validator_rejects_scope_bundle_and_capability_claims_absent_from_manifest(
        self,
    ) -> None:
        allowed_scope_urls = {
            str(scope["canonical_url"]) for scope in manifest.SCOPES_BY_ID.values()
        }
        allowed_scope_urls.update(manifest.COMPATIBILITY_SCOPE_DISCLOSURES_BY_URL)
        allowed_bundle_ids = {
            manifest.IDENTITY_BUNDLE_ID,
            manifest.CUSTOM_BUNDLE_ID,
            *(str(preset["capability_bundle"]) for preset in manifest.PRESETS_BY_ID.values()),
            *manifest.LEGACY_BUNDLES_BY_ID,
        }
        allowed_capabilities = {
            str(value)
            for scope in manifest.SCOPES_BY_ID.values()
            for value in scope["capabilities"]
        }

        self.assertEqual(
            validator.unknown_google_manifest_claims(
                "https://www.googleapis.com/auth/gmail.modify "
                "google_workspace_inbox_manager_v1 "
                "google-capability:gmail_inbox_management",
                allowed_scope_urls=allowed_scope_urls,
                allowed_bundle_ids=allowed_bundle_ids,
                allowed_capabilities=allowed_capabilities,
            ),
            (),
        )
        self.assertEqual(
            validator.unknown_google_manifest_claims(
                "https://www.googleapis.com/auth/contacts.readonly "
                "google_workspace_contacts_manager_v1 "
                "google-capability:contacts_management",
                allowed_scope_urls=allowed_scope_urls,
                allowed_bundle_ids=allowed_bundle_ids,
                allowed_capabilities=allowed_capabilities,
            ),
            (
                "bundle:google_workspace_contacts_manager_v1",
                "capability:contacts_management",
                "scope:https://www.googleapis.com/auth/contacts.readonly",
            ),
        )

    def test_compatibility_disclosures_never_become_capabilities_or_requests(self) -> None:
        implemented_urls = set(manifest.SCOPES_BY_URL)
        compatibility_urls = set(manifest.COMPATIBILITY_SCOPE_DISCLOSURES_BY_URL)
        self.assertTrue(compatibility_urls)
        self.assertFalse(implemented_urls & compatibility_urls)
        for scope_url, disclosure in manifest.COMPATIBILITY_SCOPE_DISCLOSURES_BY_URL.items():
            with self.subTest(scope_url=scope_url):
                self.assertEqual(disclosure["status"], "historical_disclosure_only")
                self.assertNotIn("capabilities", disclosure)
                self.assertNotIn("operations", disclosure)
                resolution = manifest.resolve_scope_request(
                    scope_urls=(scope_url,),
                    client_policy_id="tinyhat-development",
                )
                self.assertFalse(resolution.approved)
                self.assertEqual(len(resolution.blocked), 1)
                self.assertIsNone(resolution.blocked[0].scope_id)

    def test_drive_file_copy_includes_both_google_access_paths(self) -> None:
        drive_file = manifest.SCOPES_BY_ID["drive.file"]
        data_read = " ".join(drive_file["data_read"])
        self.assertIn("Files Tinyhat creates", data_read)
        self.assertIn("files the user explicitly shares with the app", data_read)
        self.assertIn("files you explicitly share with the app", drive_file["user_copy"])
        self.assertIn(
            "files you explicitly share with the app",
            manifest.PRESETS_BY_ID["file_collaborator"]["user_copy"],
        )

    def test_validator_entrypoints_reject_constructed_undeclared_scope_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied_root = Path(directory) / "tinyhat"
            shutil.copytree(
                REPO_ROOT,
                copied_root,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )
            workspace_path = copied_root / "google_workspace.py"
            workspace_path.write_text(
                workspace_path.read_text(encoding="utf-8")
                + '\nGOOGLE_UNDECLARED_SCOPE = f"{GOOGLE_SCOPE_PREFIX}contacts.readonly"\n',
                encoding="utf-8",
            )

            with mock.patch.object(validator, "repo_root", return_value=copied_root):
                direct_stderr = io.StringIO()
                with redirect_stderr(direct_stderr), self.assertRaises(SystemExit):
                    validator.validate_google_scope_manifest(copied_root)
                self.assertIn(
                    "scope:https://www.googleapis.com/auth/contacts.readonly",
                    direct_stderr.getvalue(),
                )

                main_stderr = io.StringIO()
                with redirect_stderr(main_stderr), self.assertRaises(SystemExit):
                    validator.main()
                self.assertIn(
                    "scope:https://www.googleapis.com/auth/contacts.readonly",
                    main_stderr.getvalue(),
                )

    def test_phase_one_atoms_and_review_only_entries_are_explicit(self) -> None:
        phase_one = {
            "gmail.readonly",
            "gmail.send",
            "gmail.compose",
            "gmail.labels",
            "gmail.modify",
            "calendar.events.readonly",
            "calendar.events",
            "drive.file",
            "drive.readonly",
        }
        for scope_id in phase_one:
            scope = manifest.SCOPES_BY_ID[scope_id]
            self.assertEqual(
                scope["client_states"]["tinyhat-development"]["request_state"],
                "approved",
            )
            self.assertEqual(
                scope["client_states"]["tinyhat-production"]["request_state"],
                "approved",
            )
        self.assertEqual(
            manifest.SCOPES_BY_ID["tasks"]["client_states"]["tinyhat-production"]["request_state"],
            "review_required",
        )
        self.assertIn(
            "not implemented", manifest.SCOPES_BY_ID["tasks"]["implemented_feature"].lower()
        )
        self.assertEqual(
            manifest.SCOPES_BY_ID["calendar.readonly"]["client_states"]["tinyhat-production"][
                "request_state"
            ],
            "legacy_only",
        )

    def test_normalization_is_deterministic_and_removes_superseded_scopes(self) -> None:
        normalized = manifest.normalize_scope_urls(
            (
                "https://www.googleapis.com/auth/calendar.events.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.labels",
                "https://www.googleapis.com/auth/gmail.compose",
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/userinfo.email",
            )
        )
        self.assertEqual(
            normalized,
            (
                "openid",
                "email",
                "profile",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/calendar.events",
            ),
        )

    def test_normalization_removes_transitive_supersession_independent_of_order(self) -> None:
        modify_url = "https://www.googleapis.com/auth/gmail.modify"
        compose_url = "https://www.googleapis.com/auth/gmail.compose"
        send_url = "https://www.googleapis.com/auth/gmail.send"
        modify = dict(manifest.SCOPES_BY_ID["gmail.modify"])
        modify["supersedes"] = ("gmail.compose",)
        modified_by_id = dict(manifest.SCOPES_BY_ID)
        modified_by_id["gmail.modify"] = MappingProxyType(modify)
        modified_by_url = dict(manifest.SCOPES_BY_URL)
        modified_by_url[modify_url] = modified_by_id["gmail.modify"]
        ancestor_first_order = (
            *manifest.IDENTITY_SCOPE_URLS,
            modify_url,
            compose_url,
            send_url,
            *(
                scope_url
                for scope_url in manifest.SCOPE_ORDER
                if scope_url
                not in {*manifest.IDENTITY_SCOPE_URLS, modify_url, compose_url, send_url}
            ),
        )

        with (
            mock.patch.object(
                manifest,
                "SCOPES_BY_ID",
                MappingProxyType(modified_by_id),
            ),
            mock.patch.object(
                manifest,
                "SCOPES_BY_URL",
                MappingProxyType(modified_by_url),
            ),
            mock.patch.object(manifest, "SCOPE_ORDER", ancestor_first_order),
        ):
            normalized = manifest.normalize_scope_urls((send_url, compose_url, modify_url))

        self.assertEqual(normalized, (*manifest.IDENTITY_SCOPE_URLS, modify_url))

    def test_normalization_preserves_arbitrary_canonical_scopes_for_review(self) -> None:
        normalized = manifest.normalize_scope_urls(
            (
                "https://www.googleapis.com/auth/z.future",
                "https://www.googleapis.com/auth/a.future",
            )
        )
        self.assertEqual(
            normalized,
            (
                "openid",
                "email",
                "profile",
                "https://www.googleapis.com/auth/a.future",
                "https://www.googleapis.com/auth/z.future",
            ),
        )
        resolved = manifest.resolve_scope_request(scope_urls=normalized)
        self.assertFalse(resolved.approved)
        self.assertEqual(
            tuple(item.scope_url for item in resolved.blocked),
            (
                "https://www.googleapis.com/auth/a.future",
                "https://www.googleapis.com/auth/z.future",
            ),
        )
        self.assertTrue(all(item.request_state == "review_required" for item in resolved.blocked))

    def test_historical_google_scope_urls_remain_representable_but_blocked(self) -> None:
        legacy = (
            "https://mail.google.com/",
            "https://www.google.com/calendar/feeds",
            "https://www.google.com/m8/feeds",
        )
        resolved = manifest.resolve_scope_request(
            scope_urls=legacy,
            client_policy_id="tinyhat-development",
        )
        self.assertFalse(resolved.approved)
        self.assertEqual(
            tuple(item.scope_url for item in resolved.blocked),
            tuple(sorted(legacy)),
        )
        self.assertTrue(all(item.scope_id is None for item in resolved.blocked))

    def test_single_preset_uses_its_bundle_and_development_policy(self) -> None:
        resolved = manifest.resolve_scope_request(
            preset_ids=("workspace_reader",),
            client_policy_id="tinyhat-development",
        )
        self.assertEqual(resolved.bundle_id, "google_workspace_workspace_reader_v1")
        self.assertEqual(resolved.access_label, "Workspace Reader")
        self.assertEqual(resolved.selected_preset_ids, ("workspace_reader",))
        self.assertEqual(resolved.services, ("identity", "gmail", "calendar", "drive"))
        self.assertTrue(resolved.read_only)
        self.assertTrue(resolved.approved)

    def test_preset_and_custom_scopes_union_into_custom_bundle(self) -> None:
        resolved = manifest.resolve_scope_request(
            preset_ids=("mail_writer", "calendar_coordinator"),
            scope_urls=("https://www.googleapis.com/auth/drive.file",),
            client_policy_id="tinyhat-development",
        )
        self.assertEqual(
            resolved.selected_preset_ids,
            ("mail_writer", "calendar_coordinator"),
        )
        self.assertEqual(resolved.bundle_id, "google_workspace_custom_v1")
        self.assertEqual(resolved.access_label, "Custom Google access")
        self.assertEqual(resolved.services, ("identity", "gmail", "calendar", "drive"))
        self.assertIn("gmail_drafts", resolved.capabilities)
        self.assertIn("calendar_event_write", resolved.capabilities)
        self.assertIn("drive_file_collaboration", resolved.capabilities)
        self.assertFalse(resolved.read_only)
        self.assertTrue(resolved.approved)

    def test_production_allows_implemented_scopes_while_verification_is_pending(
        self,
    ) -> None:
        resolved = manifest.resolve_scope_request(preset_ids=("workspace_reader",))
        self.assertTrue(resolved.approved)
        self.assertTrue(resolved.read_only)
        self.assertEqual(resolved.blocked, ())
        for scope_id in ("gmail.readonly", "calendar.events.readonly", "drive.readonly"):
            state = manifest.SCOPES_BY_ID[scope_id]["client_states"]["tinyhat-production"]
            self.assertEqual(state["request_state"], "approved")
            self.assertEqual(state["verification_state"], "preparing_submission")

    def test_manifest_listed_tasks_is_explainable_but_blocked(self) -> None:
        scope_url = "https://www.googleapis.com/auth/tasks"
        blocked = manifest.blocked_scope_details(
            (scope_url,), client_policy_id="tinyhat-development"
        )
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].scope_id, "tasks")
        self.assertEqual(blocked[0].display_name, "Manage Google Tasks")
        self.assertEqual(blocked[0].request_state, "review_required")
        self.assertEqual(blocked[0].verification_state, "not_submitted")

    def test_invalid_preset_policy_and_scope_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown Google Workspace preset"):
            manifest.resolve_scope_request(preset_ids=("missing",))
        with self.assertRaisesRegex(ValueError, "Unknown Google OAuth client policy"):
            manifest.resolve_scope_request(client_policy_id="missing")
        with self.assertRaisesRegex(ValueError, "Invalid canonical Google OAuth scope"):
            manifest.resolve_scope_request(scope_urls=("https://example.com/auth/tasks",))
        with self.assertRaisesRegex(ValueError, "Invalid canonical Google OAuth scope"):
            manifest.resolve_scope_request(scope_urls=("https://www.googleapis.com/auth/tasks ",))

    def test_legacy_fixed_bundles_reconstruct_exactly_without_normalizing(self) -> None:
        readonly = manifest.legacy_scope_urls("google_workspace_readonly_v1")
        self.assertEqual(
            readonly,
            (
                "openid",
                "email",
                "profile",
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
            ),
        )
        self.assertEqual(
            manifest.legacy_bundle_for_profile("workspace_readonly")["id"],
            "google_workspace_readonly_v1",
        )
        with self.assertRaisesRegex(ValueError, "only valid for a saved-grant"):
            manifest.legacy_scope_urls(
                "google_workspace_readonly_v1",
                saved_scope_urls=("https://www.googleapis.com/auth/tasks",),
            )

    def test_legacy_custom_bundle_preserves_exact_saved_grant_order(self) -> None:
        saved = (
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://mail.google.com/",
            "https://www.google.com/calendar/feeds",
            "https://www.googleapis.com/auth/tasks",
            "https://www.googleapis.com/auth/tasks",
        )
        self.assertEqual(
            manifest.legacy_scope_urls("google_workspace_custom_v1", saved_scope_urls=saved),
            saved[:-1],
        )
        with self.assertRaisesRegex(ValueError, "requires saved_scope_urls"):
            manifest.legacy_scope_urls("google_workspace_custom_v1")

    def test_strict_loader_rejects_missing_evidence_field(self) -> None:
        raw = self.raw_manifest()
        del raw["scopes"][0]["why_narrower_insufficient"]  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "why_narrower_insufficient"):
            self.load_changed(raw)

    def test_strict_loader_rejects_approval_with_disallowed_verification_state(
        self,
    ) -> None:
        raw = self.raw_manifest()
        gmail_readonly = next(
            scope
            for scope in raw["scopes"]  # type: ignore[union-attr]
            if scope["id"] == "gmail.readonly"
        )
        gmail_readonly["client_states"]["tinyhat-production"]["verification_state"] = (
            "not_submitted"
        )
        with self.assertRaisesRegex(ValueError, "approved request"):
            self.load_changed(raw)

    def test_strict_loader_rejects_duplicate_scope_url(self) -> None:
        raw = self.raw_manifest()
        raw["scopes"][4]["canonical_url"] = raw["scopes"][3]["canonical_url"]  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "canonical scope URLs must be unique"):
            self.load_changed(raw)

    def test_strict_loader_rejects_preset_membership_drift(self) -> None:
        raw = self.raw_manifest()
        raw["presets"][0]["scope_ids"] = ["gmail.readonly"]  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "required preset contract"):
            self.load_changed(raw)

    def test_strict_loader_rejects_preset_risk_or_default_drift(self) -> None:
        raw = self.raw_manifest()
        raw["presets"][0]["risk_class"] = "sensitive"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "highest-risk member scope"):
            self.load_changed(raw)

        raw = self.raw_manifest()
        raw["presets"][0]["default"] = True  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "default status drifted"):
            self.load_changed(raw)


if __name__ == "__main__":
    unittest.main()
