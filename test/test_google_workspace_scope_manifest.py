"""Tests for the public Google Workspace OAuth scope manifest."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType

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
        self.assertEqual(manifest.MANIFEST["manifest_version"], "1.0.0")
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
                "gmail.readonly",
                "calendar.events.readonly",
                "drive.readonly",
            ),
            "mail_writer": ("gmail.compose",),
            "inbox_manager": ("gmail.modify",),
            "calendar_coordinator": ("calendar.events",),
            "file_collaborator": ("drive.file",),
        }
        self.assertEqual(set(manifest.PRESETS_BY_ID), set(expected))
        for preset_id, scope_ids in expected.items():
            self.assertEqual(tuple(manifest.PRESETS_BY_ID[preset_id]["scope_ids"]), scope_ids)

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
                "review_required",
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

    def test_production_blocks_workspace_scopes_until_client_verification(self) -> None:
        resolved = manifest.resolve_scope_request(preset_ids=("workspace_reader",))
        self.assertFalse(resolved.approved)
        self.assertTrue(resolved.read_only)
        self.assertEqual(len(resolved.blocked), 3)
        self.assertTrue(all(item.request_state == "review_required" for item in resolved.blocked))
        self.assertTrue(
            all(item.verification_state == "preparing_submission" for item in resolved.blocked)
        )

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

    def test_strict_loader_rejects_contradictory_production_approval(self) -> None:
        raw = self.raw_manifest()
        gmail_readonly = next(
            scope
            for scope in raw["scopes"]  # type: ignore[union-attr]
            if scope["id"] == "gmail.readonly"
        )
        gmail_readonly["client_states"]["tinyhat-production"]["request_state"] = "approved"
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


if __name__ == "__main__":
    unittest.main()
