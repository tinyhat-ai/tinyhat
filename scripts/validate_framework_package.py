#!/usr/bin/env python3
"""Validate the fresh Hermes-only Tinyhat plugin package shape."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

VERSION_SHAPE = re.compile(r"^\d+\.\d+\.\d+$")
CODEX_SCREENSHOT_MIN_BYTES = 10_000
REQUIRED_TOOLS = [
    "tinyhat_plugin_version",
    "tinyhat_get_platform_status",
    "tinyhat_hats",
    "tinyhat_tell_joke",
    "tinyhat_skill_catalog",
    "tinyhat_private_secret_handoff",
    "tinyhat_slack_connect",
    "tinyhat_slack_disconnect",
    "tinyhat_credentials",
    "tinyhat_google_workspace",
    "tinyhat_google_workspace_app",
    "tinyhat_google_workspace_app_manager",
    "tinyhat_codex_auth",
    "tinyhat_plugin_update",
]
REQUIRED_COMMANDS = [
    "tinyhat-joke",
    "tinyhat-plugin-version",
    "tinyhat-secret",
]
REQUIRED_SKILLS = [
    "hat-authoring",
    "tinyhat-plugin-version",
    "tinyhat-tell-joke",
    "tinyhat-skill-catalog",
    "tinyhat-skill-authoring",
    "tinyhat-private-secret",
    "tinyhat-slack",
    "tinyhat-credentials",
    "tinyhat-google-workspace",
    "tinyhat-google-workspace-app-manager",
    "tinyhat-codex-auth",
    "tinyhat-plugin-update",
    "tinyhat-platform",
    "tinyhat-privacy",
]
FORBIDDEN_PATHS = (
    "openclaw.plugin.json",
    "src",
    ".claude",
    "roadmap",
)
FORBIDDEN_TEXT = ("CLAUDE_PLUGIN_DATA",)

GOOGLE_SCOPE_MANIFEST_PATH = "google_workspace_scope_manifest.json"
GOOGLE_SCOPE_MANIFEST_LOADER_PATH = "google_workspace_scope_manifest.py"
GOOGLE_SCOPE_MANIFEST_SCHEMA = "tinyhat_google_workspace_scope_manifest_v1"
GOOGLE_IDENTITY_BUNDLE_ID = "google_workspace_identity_v1"
GOOGLE_CUSTOM_BUNDLE_ID = "google_workspace_custom_v1"
GOOGLE_IDENTITY_SCOPE_IDS = ("openid", "email", "profile")
GOOGLE_REQUIRED_PRESETS = {
    "mail_reader": (
        "Mail Reader",
        "google_workspace_mail_reader_v1",
        ("gmail.readonly",),
        "restricted",
    ),
    "mail_sender": (
        "Mail Sender",
        "google_workspace_mail_sender_v1",
        ("gmail.send",),
        "sensitive",
    ),
    "workspace_reader": (
        "Workspace Reader",
        "google_workspace_workspace_reader_v1",
        ("gmail.readonly", "calendar.events.readonly", "drive.readonly"),
        "restricted",
    ),
    "mail_writer": (
        "Mail Writer",
        "google_workspace_mail_writer_v1",
        ("gmail.compose",),
        "restricted",
    ),
    "inbox_manager": (
        "Inbox Manager",
        "google_workspace_inbox_manager_v1",
        ("gmail.modify",),
        "restricted",
    ),
    "calendar_coordinator": (
        "Calendar Coordinator",
        "google_workspace_calendar_coordinator_v1",
        ("calendar.events",),
        "sensitive",
    ),
    "file_collaborator": (
        "File Collaborator",
        "google_workspace_file_collaborator_v1",
        ("drive.file",),
        "non_sensitive",
    ),
}
GOOGLE_REQUIRED_LEGACY_BUNDLES = {
    "google_workspace_recommended_v1": ("workspace_recommended",),
    "google_workspace_readonly_v1": ("workspace_readonly",),
    "google_workspace_gmail_send_v1": ("gmail_send",),
    "google_workspace_calendar_write_v1": ("calendar_write",),
    "google_workspace_gmail_send_calendar_write_v1": ("gmail_send_calendar_write",),
    "google_workspace_custom_v1": ("workspace_custom",),
}
GOOGLE_MANIFEST_DOC_PATHS = (
    "README.md",
    "schemas.py",
    "context.py",
    "docs/capabilities.md",
    "docs/runtime-boundary.md",
    "docs/skill-authoring.md",
    "skills/tinyhat-google-workspace/SKILL.md",
    "skills/tinyhat-platform/SKILL.md",
)
GOOGLE_SCOPE_URL_PATTERN = re.compile(
    r"(?:https://www\.googleapis\.com/auth/[A-Za-z0-9][A-Za-z0-9._/-]*"
    r"|https://mail\.google\.com/"
    r"|https://www\.google\.com/(?:calendar/feeds|m8/feeds))"
)
GOOGLE_BUNDLE_ID_PATTERN = re.compile(r"\bgoogle_workspace_[a-z0-9_]+_v[0-9]+\b")
GOOGLE_CAPABILITY_MARKER_PATTERN = re.compile(r"\bgoogle-capability:([a-z][a-z0-9_]*)\b")
GOOGLE_SCOPE_MARKER_PATTERN = re.compile(r"\bgoogle-scope:([a-z][a-z0-9_.-]*)\b")
GOOGLE_DRIVE_FILE_COPY_PATHS = (
    GOOGLE_SCOPE_MANIFEST_PATH,
    "README.md",
    "schemas.py",
    "google_workspace.py",
    "docs/capabilities.md",
    "docs/runtime-boundary.md",
    "docs/skill-authoring.md",
    "skills/tinyhat-google-workspace/SKILL.md",
    "skills/tinyhat-platform/SKILL.md",
)


def fail(message: str) -> None:
    print(f"framework-package: {message}", file=sys.stderr)
    raise SystemExit(1)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def unknown_google_manifest_claims(
    text: str,
    *,
    allowed_scope_urls: set[str],
    allowed_bundle_ids: set[str],
    allowed_capabilities: set[str],
    python_source: bool = False,
) -> tuple[str, ...]:
    """Return structured Google scope, bundle, or capability claims absent from the manifest."""

    scope_urls = set(GOOGLE_SCOPE_URL_PATTERN.findall(text))
    if python_source:
        scope_urls.update(_statically_constructed_google_scope_urls(text))
    unknown = {
        *(f"scope:{value}" for value in scope_urls if value not in allowed_scope_urls),
        *(
            f"bundle:{value}"
            for value in GOOGLE_BUNDLE_ID_PATTERN.findall(text)
            if value not in allowed_bundle_ids
        ),
        *(
            f"capability:{value}"
            for value in GOOGLE_CAPABILITY_MARKER_PATTERN.findall(text)
            if value not in allowed_capabilities
        ),
    }
    return tuple(sorted(unknown))


def _static_python_string(node: ast.AST, constants: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                part = _static_python_string(value.value, constants)
            else:
                part = _static_python_string(value, constants)
            if part is None:
                return None
            parts.append(part)
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_python_string(node.left, constants)
        right = _static_python_string(node.right, constants)
        if left is not None and right is not None:
            return left + right
    return None


def _statically_constructed_python_strings(text: str) -> set[str]:
    """Resolve the statically knowable strings in one Python module."""

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        fail(f"could not parse Python while checking Google scope claims: {exc}")
    assignments: list[tuple[str, ast.AST]] = []
    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            value = statement.value
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if value is None:
                continue
            assignments.extend(
                (target.id, value) for target in targets if isinstance(target, ast.Name)
            )
    constants: dict[str, str] = {}
    for _ in range(len(assignments) + 1):
        changed = False
        for name, value_node in assignments:
            value = _static_python_string(value_node, constants)
            if value is not None and constants.get(name) != value:
                constants[name] = value
                changed = True
        if not changed:
            break
    strings: set[str] = set()
    for node in ast.walk(tree):
        value = _static_python_string(node, constants)
        if value is not None:
            strings.add(value)
    return strings


def _statically_constructed_google_scope_urls(text: str) -> set[str]:
    """Find literal or constructed Google scope claims in one Python module."""

    urls: set[str] = set()
    for value in _statically_constructed_python_strings(text):
        urls.update(GOOGLE_SCOPE_URL_PATTERN.findall(value))
    return urls


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"could not read {path.relative_to(repo_root())}: {exc}")
    except json.JSONDecodeError as exc:
        fail(f"{path.relative_to(repo_root())} is invalid JSON: {exc}")
    require(isinstance(value, dict), f"{path.relative_to(repo_root())} must be an object")
    return value


def read_pyproject_version(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, flags=re.MULTILINE)
    require(match is not None, "pyproject.toml must define project.version")
    return match.group(1)


def read_plugin_yaml(root: Path) -> dict[str, object]:
    text = (root / "plugin.yaml").read_text(encoding="utf-8")
    data: dict[str, object] = {}
    current_list: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_list:
            items = data.setdefault(current_list, [])
            require(isinstance(items, list), f"plugin.yaml {current_list} must be a list")
            items.append(stripped[2:].strip())
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            current_list = key if not value.strip() else None
            data[key] = [] if current_list else value.strip()
    return data


def index_objects_by_id(items: object, *, label: str) -> dict[str, dict[str, object]]:
    require(isinstance(items, list), f"{label} must be a list")
    indexed: dict[str, dict[str, object]] = {}
    for item in items:
        require(isinstance(item, dict), f"{label} entries must be objects")
        item_id = item.get("id")
        require(isinstance(item_id, str) and item_id, f"{label} entries need string ids")
        require(item_id not in indexed, f"{label} contains duplicate id {item_id}")
        indexed[item_id] = item
    return indexed


def load_python_module_namespace(path: Path) -> dict[str, object]:
    module_name = "_tinyhat_scope_manifest_package_validator"
    spec = importlib.util.spec_from_file_location(module_name, path)
    require(spec is not None and spec.loader is not None, f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return vars(module)


def validate_google_scope_manifest(root: Path) -> None:  # noqa: PLR0912, PLR0915
    manifest_path = root / GOOGLE_SCOPE_MANIFEST_PATH
    loader_path = root / GOOGLE_SCOPE_MANIFEST_LOADER_PATH
    require(manifest_path.is_file(), f"{GOOGLE_SCOPE_MANIFEST_PATH} is missing")
    require(loader_path.is_file(), f"{GOOGLE_SCOPE_MANIFEST_LOADER_PATH} is missing")

    manifest = read_json(manifest_path)
    require(manifest.get("schema") == GOOGLE_SCOPE_MANIFEST_SCHEMA, "Google scope schema drift")
    manifest_version = manifest.get("manifest_version")
    require(
        isinstance(manifest_version, str) and VERSION_SHAPE.fullmatch(manifest_version),
        "Google scope manifest version must be semantic MAJOR.MINOR.PATCH",
    )
    require(
        manifest.get("identity_scope_ids") == list(GOOGLE_IDENTITY_SCOPE_IDS),
        "Google identity baseline drift",
    )
    require(
        manifest.get("identity_capability_bundle") == GOOGLE_IDENTITY_BUNDLE_ID,
        "Google identity bundle id drift",
    )

    custom_policy = manifest.get("custom_scope_policy")
    require(isinstance(custom_policy, dict), "custom_scope_policy must be an object")
    require(
        custom_policy.get("unknown_scope_request_state") == "review_required",
        "unknown Google scopes must stop with review_required",
    )

    clients = index_objects_by_id(manifest.get("client_policies"), label="client_policies")
    require(
        set(clients) == {"tinyhat-development", "tinyhat-production"},
        "Google OAuth client policy ids drift",
    )
    production_client = clients["tinyhat-production"]
    require(
        production_client.get("environment") == "production",
        "tinyhat-production client policy must target production",
    )
    production_allowed_states = production_client.get("allowed_request_states")
    require(
        production_allowed_states == ["approved"],
        "production Google requests must require the approved client state",
    )
    production_allowed_verification_states = production_client.get("allowed_verification_states")
    require(
        production_allowed_verification_states
        == ["not_required", "preparing_submission", "verified"],
        "production Google requests must distinguish pending from completed verification",
    )

    scopes = index_objects_by_id(manifest.get("scopes"), label="scopes")
    canonical_urls: set[str] = set()
    required_scope_fields = (
        "canonical_url",
        "classification",
        "enabled_api",
        "implemented_feature",
        "operations",
        "data_read",
        "data_written",
        "narrower_alternatives",
        "user_copy",
        "demo_steps",
        "verification_status",
        "supersedes",
        "client_states",
    )
    for scope_id, scope in scopes.items():
        for field in required_scope_fields:
            require(field in scope, f"scope {scope_id} is missing {field}")
        canonical_url = scope.get("canonical_url")
        require(
            isinstance(canonical_url, str) and canonical_url,
            f"scope {scope_id} needs a canonical_url",
        )
        require(canonical_url not in canonical_urls, f"duplicate canonical scope {canonical_url}")
        canonical_urls.add(canonical_url)
        require(
            scope.get("classification") in {"non_sensitive", "sensitive", "restricted"},
            f"scope {scope_id} has an invalid Google classification",
        )
        for field in (
            "operations",
            "data_read",
            "data_written",
            "narrower_alternatives",
            "demo_steps",
            "supersedes",
        ):
            require(isinstance(scope.get(field), list), f"scope {scope_id} {field} must be a list")
        require(scope.get("operations"), f"scope {scope_id} needs implemented operations")
        require(scope.get("demo_steps"), f"scope {scope_id} needs demo steps")
        client_states = scope.get("client_states")
        require(
            isinstance(client_states, dict), f"scope {scope_id} client_states must be an object"
        )
        require(
            set(client_states) == set(clients), f"scope {scope_id} client policy coverage drift"
        )
        for client_id, state in client_states.items():
            require(
                isinstance(state, dict), f"scope {scope_id} {client_id} state must be an object"
            )
            require(
                isinstance(state.get("request_state"), str),
                f"scope {scope_id} {client_id} needs request_state",
            )
            require(
                isinstance(state.get("verification_state"), str),
                f"scope {scope_id} {client_id} needs verification_state",
            )
        production_state = client_states["tinyhat-production"]
        request_allowed = production_state["request_state"] in set(production_allowed_states)
        verification_allowed = production_state["verification_state"] in set(
            production_allowed_verification_states
        )
        require(
            not request_allowed or verification_allowed,
            f"scope {scope_id} is requestable before its verification state allows it",
        )

    compatibility_rows = manifest.get("compatibility_scope_disclosures")
    require(
        isinstance(compatibility_rows, list),
        "compatibility_scope_disclosures must be a list",
    )
    compatibility_by_url: dict[str, dict[str, object]] = {}
    compatibility_keys = {
        "canonical_url",
        "service",
        "status",
        "user_copy",
        "rationale",
    }
    for row in compatibility_rows:
        require(isinstance(row, dict), "compatibility scope disclosures must be objects")
        require(
            set(row) == compatibility_keys,
            "compatibility scope disclosures must remain disclosure-only records",
        )
        scope_url = row.get("canonical_url")
        require(
            isinstance(scope_url, str) and scope_url,
            "compatibility scope disclosures need canonical URLs",
        )
        require(
            scope_url not in compatibility_by_url,
            f"duplicate compatibility scope disclosure {scope_url}",
        )
        require(
            scope_url not in canonical_urls,
            f"compatibility disclosure {scope_url} cannot be an implemented scope",
        )
        require(
            row.get("status") == "historical_disclosure_only",
            f"compatibility disclosure {scope_url} must remain historical_disclosure_only",
        )
        for field in ("service", "user_copy", "rationale"):
            require(
                isinstance(row.get(field), str) and row[field],
                f"compatibility disclosure {scope_url} needs {field}",
            )
        compatibility_by_url[scope_url] = row

    expected_supersets = {
        "gmail.modify": ("gmail.readonly", "gmail.compose", "gmail.send", "gmail.labels"),
        "gmail.compose": ("gmail.send",),
        "calendar.events": ("calendar.events.readonly",),
    }
    for scope_id, superseded in expected_supersets.items():
        require(scope_id in scopes, f"normalizing scope {scope_id} is missing")
        require(
            scopes[scope_id].get("supersedes") == list(superseded),
            f"scope normalization drift for {scope_id}",
        )

    presets = index_objects_by_id(manifest.get("presets"), label="presets")
    require(list(presets) == list(GOOGLE_REQUIRED_PRESETS), "Google preset id or order drift")
    for preset_id, (
        display_name,
        bundle_id,
        scope_ids,
        risk_class,
    ) in GOOGLE_REQUIRED_PRESETS.items():
        preset = presets[preset_id]
        require(preset.get("display_name") == display_name, f"{preset_id} display name drift")
        require(preset.get("capability_bundle") == bundle_id, f"{preset_id} bundle id drift")
        require(preset.get("scope_ids") == list(scope_ids), f"{preset_id} scope membership drift")
        require(preset.get("risk_class") == risk_class, f"{preset_id} risk class drift")
        require(preset.get("recommended") is True, f"{preset_id} must remain recommended")
        require(preset.get("default") is False, f"{preset_id} must not become the default")
        for scope_id in scope_ids:
            require(scope_id in scopes, f"{preset_id} references unknown scope {scope_id}")

    tasks = scopes.get("tasks")
    require(tasks is not None, "manifest needs the Google Tasks review-required proof scope")
    require(
        tasks.get("canonical_url") == "https://www.googleapis.com/auth/tasks",
        "Google Tasks proof scope URL drift",
    )
    require(
        tasks["client_states"]["tinyhat-production"]["request_state"] == "review_required",
        "Google Tasks must remain blocked before production OAuth",
    )
    phase_one_scope_ids = {
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
    for scope_id in phase_one_scope_ids:
        state = scopes[scope_id]["client_states"]["tinyhat-production"]
        require(
            state
            == {
                "request_state": "approved",
                "verification_state": "preparing_submission",
            },
            f"implemented production scope {scope_id} must remain requestable while review is pending",
        )

    legacy_bundles = index_objects_by_id(manifest.get("legacy_bundles"), label="legacy_bundles")
    require(
        set(legacy_bundles) == set(GOOGLE_REQUIRED_LEGACY_BUNDLES),
        "historical Google bundle ids drift",
    )
    for bundle_id, profile_ids in GOOGLE_REQUIRED_LEGACY_BUNDLES.items():
        bundle = legacy_bundles[bundle_id]
        require(
            bundle.get("profile_ids") == list(profile_ids), f"{bundle_id} profile mapping drift"
        )
        require(bundle.get("requestable") is False, f"{bundle_id} must be compatibility-only")
        bundle_scope_ids = bundle.get("scope_ids")
        require(isinstance(bundle_scope_ids, list), f"{bundle_id} scope_ids must be a list")
        for scope_id in bundle_scope_ids:
            require(scope_id in scopes, f"{bundle_id} references unknown scope {scope_id}")

    loader = load_python_module_namespace(loader_path)
    loader_manifest = loader.get("MANIFEST")
    require(isinstance(loader_manifest, Mapping), "loader MANIFEST missing")
    require(
        Path(loader.get("MANIFEST_PATH", "")).resolve() == manifest_path.resolve(),
        "scope loader MANIFEST_PATH drift",
    )
    load_manifest = loader.get("load_manifest")
    require(callable(load_manifest), "scope loader is missing load_manifest")
    require(
        load_manifest(manifest_path) == loader_manifest,
        "scope loader does not reproduce its packaged manifest",
    )
    require(
        loader_manifest.get("schema") == manifest.get("schema"), "scope loader schema bytes drift"
    )
    require(
        loader_manifest.get("manifest_version") == manifest.get("manifest_version"),
        "scope loader version bytes drift",
    )
    require(loader.get("MANIFEST_SCHEMA") == GOOGLE_SCOPE_MANIFEST_SCHEMA, "loader schema drift")
    require(
        loader.get("IDENTITY_BUNDLE_ID") == GOOGLE_IDENTITY_BUNDLE_ID,
        "loader identity bundle drift",
    )
    require(loader.get("CUSTOM_BUNDLE_ID") == GOOGLE_CUSTOM_BUNDLE_ID, "loader custom bundle drift")
    require(
        loader.get("IDENTITY_SCOPE_IDS") == GOOGLE_IDENTITY_SCOPE_IDS, "loader identity ids drift"
    )
    require(
        loader.get("PRESET_ORDER") == tuple(GOOGLE_REQUIRED_PRESETS), "loader preset order drift"
    )
    require(set(loader.get("SCOPES_BY_ID", {})) == set(scopes), "loader scope index drift")
    require(set(loader.get("PRESETS_BY_ID", {})) == set(presets), "loader preset index drift")
    require(
        set(loader.get("CLIENT_POLICIES_BY_ID", {})) == set(clients), "loader client index drift"
    )
    require(
        set(loader.get("LEGACY_BUNDLES_BY_ID", {})) == set(legacy_bundles),
        "loader legacy bundle index drift",
    )
    require(
        set(loader.get("COMPATIBILITY_SCOPE_DISCLOSURES_BY_URL", {})) == set(compatibility_by_url),
        "loader compatibility disclosure index drift",
    )
    for helper in (
        "load_manifest",
        "normalize_scope_urls",
        "preset_scope_urls",
        "blocked_scope_details",
        "resolve_scope_request",
        "approved_scope_urls",
    ):
        require(callable(loader.get(helper)), f"scope loader is missing {helper}")

    resolve_scope_request = loader["resolve_scope_request"]
    for scope_url in compatibility_by_url:
        resolution = resolve_scope_request(
            scope_urls=(scope_url,),
            client_policy_id="tinyhat-development",
        )
        require(
            not resolution.approved
            and len(resolution.blocked) == 1
            and resolution.blocked[0].scope_id is None,
            f"compatibility disclosure {scope_url} became requestable or implemented",
        )

    allowed_scope_urls = {
        value
        for scope in scopes.values()
        for value in (scope["canonical_url"], *scope.get("aliases", []))
        if isinstance(value, str)
    }
    allowed_scope_urls.update(compatibility_by_url)
    allowed_bundle_ids = {
        GOOGLE_IDENTITY_BUNDLE_ID,
        GOOGLE_CUSTOM_BUNDLE_ID,
        *legacy_bundles,
        *(str(preset["capability_bundle"]) for preset in presets.values()),
    }
    allowed_capabilities = {
        str(value) for scope in scopes.values() for value in scope.get("capabilities", [])
    }
    claim_paths = {
        *(root / rel for rel in GOOGLE_MANIFEST_DOC_PATHS),
        *root.glob("*.py"),
    }
    for claim_path in sorted(claim_paths):
        rel = claim_path.relative_to(root).as_posix()
        claim_text = claim_path.read_text(encoding="utf-8")
        unknown_claims = unknown_google_manifest_claims(
            claim_text,
            allowed_scope_urls=allowed_scope_urls,
            allowed_bundle_ids=allowed_bundle_ids,
            allowed_capabilities=allowed_capabilities,
            python_source=claim_path.suffix == ".py",
        )
        require(
            not unknown_claims,
            f"{rel} claims Google access absent from the manifest: {', '.join(unknown_claims)}",
        )

    capability_doc = (root / "docs/capabilities.md").read_text(encoding="utf-8")
    documented_capabilities = GOOGLE_CAPABILITY_MARKER_PATTERN.findall(capability_doc)
    require(
        set(documented_capabilities) == allowed_capabilities
        and len(documented_capabilities) == len(allowed_capabilities),
        "docs/capabilities.md Google capability marker drift",
    )
    documented_scope_ids = GOOGLE_SCOPE_MARKER_PATTERN.findall(capability_doc)
    require(
        set(documented_scope_ids) == set(scopes) and len(documented_scope_ids) == len(scopes),
        "docs/capabilities.md Google scope marker drift",
    )

    for rel in GOOGLE_DRIVE_FILE_COPY_PATHS:
        copy_path = root / rel
        copy_text = copy_path.read_text(encoding="utf-8")
        if copy_path.suffix == ".py":
            copy_text = "\n".join((copy_text, *_statically_constructed_python_strings(copy_text)))
        normalized_copy = " ".join(copy_text.lower().split())
        explicit_share_copy = (
            "files you explicitly share with the app" in normalized_copy
            or "files the user explicitly shares with the app" in normalized_copy
        )
        require(
            "files tinyhat creates" in normalized_copy and explicit_share_copy,
            f"{rel} must explain both drive.file access paths",
        )

    for rel in GOOGLE_MANIFEST_DOC_PATHS:
        text = (root / rel).read_text(encoding="utf-8")
        normalized_text = " ".join(text.split())
        for preset_id, (display_name, _, _, _) in GOOGLE_REQUIRED_PRESETS.items():
            require(preset_id in normalized_text, f"{rel} missing Google preset {preset_id}")
            if rel != "context.py":
                require(
                    display_name in normalized_text,
                    f"{rel} missing Google preset {display_name}",
                )
        require(
            "review_required" in normalized_text,
            f"{rel} missing review_required stop guidance",
        )


def validate_versions(root: Path) -> str:
    package = read_json(root / "package.json")
    hermes = read_json(root / "hermes.plugin.json")
    release_please = read_json(root / ".release-please-manifest.json")
    yaml_data = read_plugin_yaml(root)
    require(
        yaml_data.get("kind") == "standalone",
        "plugin.yaml kind must be standalone for Hermes",
    )
    version = package.get("version")
    require(isinstance(version, str), "package.json version must be a string")
    require(VERSION_SHAPE.fullmatch(version) is not None, "version must be shaped X.Y.Z")
    for label, found in (
        ("hermes.plugin.json version", hermes.get("version")),
        ("plugin.yaml version", yaml_data.get("version")),
        ("pyproject.toml project.version", read_pyproject_version(root)),
        (".release-please-manifest.json version", release_please.get(".")),
    ):
        require(found == version, f"{label} must match package.json version {version}")
    return version


def validate_hermes_adapter(root: Path) -> None:
    package = read_json(root / "package.json")
    hermes = read_json(root / "hermes.plugin.json")
    yaml_data = read_plugin_yaml(root)
    require(hermes.get("schema") == "tinyhat.framework-adapter.v1", "adapter schema drift")
    framework = hermes.get("framework")
    require(isinstance(framework, dict), "framework must be an object")
    require(framework.get("name") == "hermes", "framework.name must be hermes")

    for rel in (
        "plugin.yaml",
        "hermes.plugin.json",
        "__init__.py",
        "schemas.py",
        "tools.py",
        "platform.py",
        GOOGLE_SCOPE_MANIFEST_PATH,
        GOOGLE_SCOPE_MANIFEST_LOADER_PATH,
        "google_workspace.py",
        "google_workspace_app.py",
        "google_workspace_app_manager.py",
        "google_workspace_disconnect_worker.py",
        "google_workspace_worker.py",
        "secret_handoff.py",
        "secret_handoff_worker.py",
    ):
        require((root / rel).is_file(), f"{rel} is missing")

    package_files = package.get("files")
    require(isinstance(package_files, list), "package.json files must be a list")
    for rel in (GOOGLE_SCOPE_MANIFEST_PATH, GOOGLE_SCOPE_MANIFEST_LOADER_PATH):
        require(rel in package_files, f"package.json files must include {rel}")

    codex_screenshot = (
        root
        / "skills"
        / "tinyhat-codex-auth"
        / "assets"
        / "chatgpt-enable-device-code-for-codex.png"
    )
    require(codex_screenshot.is_file(), "Codex auth prerequisite screenshot is missing")
    require(
        codex_screenshot.stat().st_size > CODEX_SCREENSHOT_MIN_BYTES,
        "Codex auth screenshot looks empty",
    )

    entrypoint = hermes.get("entrypoint")
    require(isinstance(entrypoint, dict), "entrypoint must be an object")
    require(entrypoint.get("manifest") == "plugin.yaml", "entrypoint.manifest must be plugin.yaml")
    require(entrypoint.get("module") == "__init__.py", "entrypoint.module must be __init__.py")
    require(entrypoint.get("register") == "register", "entrypoint.register must be register")

    provided_tools = yaml_data.get("provides_tools")
    require(isinstance(provided_tools, list), "plugin.yaml provides_tools must be a list")
    require(
        provided_tools == REQUIRED_TOOLS,
        "plugin.yaml provided tools drift",
    )

    source = (root / "__init__.py").read_text(encoding="utf-8")
    for phrase in ("ctx.register_tool", "ctx.register_skill", "ctx.register_command"):
        require(phrase in source, f"__init__.py missing {phrase}")

    skills = hermes.get("skills")
    require(isinstance(skills, list), "hermes.plugin.json skills must be a list")
    skill_names = [skill.get("name") for skill in skills if isinstance(skill, dict)]
    require(skill_names == REQUIRED_SKILLS, "skill declaration drift")
    expected_skill_paths = {
        "hat-authoring": "skills/hat-authoring/SKILL.md",
        "tinyhat-plugin-version": "skills/tinyhat-plugin-version/SKILL.md",
        "tinyhat-tell-joke": "skills/tinyhat-tell-joke/SKILL.md",
        "tinyhat-skill-catalog": "skills/tinyhat-skill-catalog/SKILL.md",
        "tinyhat-skill-authoring": "skills/tinyhat-skill-authoring/SKILL.md",
        "tinyhat-private-secret": "skills/tinyhat-private-secret/SKILL.md",
        "tinyhat-slack": "skills/tinyhat-slack/SKILL.md",
        "tinyhat-credentials": "skills/tinyhat-credentials/SKILL.md",
        "tinyhat-google-workspace": "skills/tinyhat-google-workspace/SKILL.md",
        "tinyhat-google-workspace-app-manager": (
            "skills/tinyhat-google-workspace-app-manager/SKILL.md"
        ),
        "tinyhat-codex-auth": "skills/tinyhat-codex-auth/SKILL.md",
        "tinyhat-plugin-update": "skills/tinyhat-plugin-update/SKILL.md",
        "tinyhat-platform": "skills/tinyhat-platform/SKILL.md",
        "tinyhat-privacy": "skills/tinyhat-privacy/SKILL.md",
    }
    for skill in skills:
        require(isinstance(skill, dict), "skill declaration must be an object")
        name = skill.get("name")
        require(
            skill.get("path") == expected_skill_paths.get(str(name)),
            f"{name} path drift",
        )
        require(
            (root / str(skill.get("path"))).is_file(),
            f"{name} proof skill missing",
        )
        require(
            skill.get("qualified_name") == f"tinyhat:{name}",
            f"{name} qualified_name drift",
        )
        aliases = skill.get("aliases")
        require(isinstance(aliases, list), f"{name} aliases must be a list")
        require(name in aliases, f"{name} aliases must include the unqualified name")

    tools = hermes.get("tools")
    require(isinstance(tools, list), "hermes.plugin.json tools must be a list")
    tool_names = [tool.get("name") for tool in tools if isinstance(tool, dict)]
    require(tool_names == REQUIRED_TOOLS, "tool declaration drift")

    commands = hermes.get("commands")
    require(isinstance(commands, list), "hermes.plugin.json commands must be a list")
    command_names = [command.get("name") for command in commands if isinstance(command, dict)]
    require(command_names == REQUIRED_COMMANDS, "command declaration drift")


def validate_fresh_surface(root: Path) -> None:
    for rel in FORBIDDEN_PATHS:
        require(not (root / rel).exists(), f"{rel} must not exist in this fresh Hermes branch")

    skill_dirs = sorted(path.name for path in (root / "skills").iterdir() if path.is_dir())
    require(
        skill_dirs == sorted(REQUIRED_SKILLS),
        "skills directory does not match the Tinyhat public capability set",
    )

    checked_roots = [
        root / "README.md",
        root / "AGENTS.md",
        root / "CONTRIBUTING.md",
        root / "RELEASING.md",
        root / "docs",
        root / ".agents",
        root / "skills",
        root / "test",
        root / "plugin.yaml",
        root / "hermes.plugin.json",
        root / "__init__.py",
        root / "platform.py",
        root / "context.py",
        root / GOOGLE_SCOPE_MANIFEST_PATH,
        root / GOOGLE_SCOPE_MANIFEST_LOADER_PATH,
        root / "google_workspace.py",
        root / "google_workspace_app.py",
        root / "google_workspace_app_manager.py",
        root / "google_workspace_disconnect_worker.py",
        root / "google_workspace_worker.py",
        root / "hats.py",
        root / "secret_handoff.py",
        root / "secret_handoff_worker.py",
        root / "schemas.py",
        root / "tools.py",
    ]
    for base in checked_roots:
        files = [base] if base.is_file() else list(base.rglob("*"))
        for path in files:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for phrase in FORBIDDEN_TEXT:
                require(
                    phrase not in text,
                    f"{path.relative_to(root)} still references forbidden phrase {phrase!r}",
                )


def validate_docs(root: Path) -> None:
    checks = {
        "README.md": (
            "teaches an agent what the Tinyhat",
            "Hermes only",
            "tinyhat-tell-joke",
            "tinyhat-plugin-version",
            "tinyhat-skill-catalog",
            "tinyhat-skill-authoring",
            "tinyhat-private-secret",
            "tinyhat-slack",
            "tinyhat-credentials",
            "tinyhat-google-workspace",
            "tinyhat_google_workspace_app",
            "tinyhat_google_workspace_app_manager",
            "tinyhat-codex-auth",
            "tinyhat-plugin-update",
            "tinyhat-platform",
            "tinyhat-privacy",
            "hat-authoring",
            "tinyhat_hats",
            "pre_llm_call",
            "channels/lts",
            "channels/latest",
        ),
        "docs/skill-authoring.md": (
            "Tinyhat skills are public instructions",
            "Do not ask the user to paste secret values in chat.",
            "Secret Naming Standard",
            "Tinyhat Platform Context",
            "tinyhat-codex-auth",
            "tinyhat-skill-catalog",
            "tinyhat-skill-authoring",
            "tinyhat-slack",
            "tinyhat_slack_connect",
            "tinyhat-credentials",
            "tinyhat_google_workspace_app",
            "tinyhat_google_workspace_app_manager",
            "tinyhat-plugin-update",
            "tinyhat-privacy",
            "tinyhat_get_platform_status",
            "hat-authoring",
            "tinyhat_hats",
        ),
        "skills/tinyhat-platform/SKILL.md": (
            "tinyhat_get_platform_status",
            "tinyhat_skill_catalog",
            "tinyhat_slack_connect",
            "tinyhat_plugin_update",
            "tinyhat_google_workspace_app",
            "tinyhat_google_workspace_app_manager",
            "gws auth",
            "Reporting Tinyhat Bugs",
        ),
        "docs/capabilities.md": (
            "tinyhat_get_platform_status",
            "tinyhat_skill_catalog",
            "tinyhat_slack_connect",
            "tinyhat_plugin_update",
            "tinyhat_google_workspace",
            "tinyhat_google_workspace_app",
            "tinyhat_google_workspace_app_manager",
            "Plugin Update And Skill Discovery",
            "tinyhat-privacy",
            "Privacy And Trust",
            "tinyhat_hats",
        ),
        "skills/hat-authoring/SKILL.md": (
            "tinyhat_hats",
            "customer's work email",
            "create a Telegram agent that wears the hat",
            "tinyhat:tinyhat-skill-authoring",
        ),
        "skills/tinyhat-skill-authoring/SKILL.md": (
            "1-64 lowercase letters",
            "at most 1,024 characters",
            "should not trigger",
            "about 200 lines and 2,000 tokens",
            "500 lines or about 5,000 tokens",
            "progressive-disclosure",
            "Never place credentials or private keys",
        ),
        "skills/tinyhat-privacy/SKILL.md": (
            "dedicated Computer created for this user alone",
            "Tinyhat does not read the contents of a customer's Computer",
            "routine operations",
            "affirmatively requests or permits",
            "protect the service, or maintain security",
            "required by law",
            "private Computers",
            "https://tinyhat.ai/privacy",
            "https://tinyhat.ai/terms",
            "privacy@tinyloop.co",
            "Do not name individual operators",
            "Do not reassure by comparison",
        ),
        "skills/tinyhat-google-workspace/SKILL.md": (
            "existing Google account",
            "Connect my Google Workspace",
            "identity only",
            "mail_reader",
            "mail_sender",
            "workspace_reader",
            "mail_writer",
            "inbox_manager",
            "calendar_coordinator",
            "file_collaborator",
            "review_required",
            "gmail.modify",
            "Google consent is the permission decision",
            "manifest-listed canonical",
            "native Telegram inline button",
            "Never print, paste, repeat",
            "does not revoke the shared Google",
            "tinyhat_google_workspace",
            "tinyhat_google_workspace_app",
            "Hermes's bundled `google-workspace` skill",
            "Never put a dotted method identifier in `argv[0]`",
            "path and query fields in the JSON",
            "API request body in the JSON",
            "Never claim that only one service is exposed",
            "Never ask for a Google Cloud",
            "gws auth",
            "any second OAuth flow",
            '{"action": "connect"}',
            '{"action": "status"}',
            '{"action": "disconnect"}',
            "never call",
            '"confirmed": true',
            "exactly one **Revoke this Computer\u2019s access**",
            "**Confirm revoke** and **Cancel**",
            "Do not change the runtime",
        ),
        "skills/tinyhat-google-workspace-app-manager/SKILL.md": (
            "tinyhat_google_workspace_app_manager",
            '"action": "install", "confirmed": true',
            "Linux x86_64 and aarch64",
            "never run `gws auth`",
            "root-only quarantine",
        ),
        "skills/tinyhat-codex-auth/SKILL.md": (
            "For common natural-language requests, call `tinyhat_codex_auth` once",
            '{"action": "prerequisite"}',
            "caption is the user-facing reply.",
            "Keep `/codex_auth` on its own line",
            "Open `chatgpt.com`",
            "Secure sign in with ChatGPT",
            "Enable device code authorization for Codex",
            "Then come back here and tap:",
            "/codex_auth",
            "Do not call `tinyhat_codex_auth` twice",
            "Do not send an extra normal chat reply",
            '{"action": "start", "confirmed": true}',
            "tinyhat_codex_auth",
            "hermes_runtime.telegram_codex_auth start",
        ),
        ".agents/skills/tinyhat-plugin-skill-authoring/SKILL.md": (
            "Create, modify, or review Tinyhat plugin skills.",
            "Reject or clarify generic names",
        ),
        "RELEASING.md": (
            "channels/lts",
            "channels/latest",
            "codex/v0.20-hermes-plugin",
        ),
    }
    for rel, phrases in checks.items():
        text = (root / rel).read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        for phrase in phrases:
            require(phrase in normalized, f"{rel} missing phrase: {phrase}")


def validate_google_workspace_contract(root: Path) -> None:
    text = (root / "google_workspace.py").read_text(encoding="utf-8")
    required = (
        "from .google_workspace_scope_manifest import (",
        "GOOGLE_WORKSPACE_PRESETS = tuple(PRESET_ORDER)",
        "GOOGLE_LEGACY_PROFILE_CONFIGS = {",
        "legacy_profile=True",
        'raw_presets = payload.get("presets")',
        "resolve_scope_request(",
        "blocked_scope_details(",
        "class GoogleWorkspaceScopeReviewRequired",
        "_scope_review_required_payload(",
        '"status": "review_required"',
        '"button_sent": False',
        "_profile_for_capability_bundle(",
        "_profile_for_scope_set(",
        "TINYHAT_GOOGLE_PREPARE_PATH =",
        "GOOGLE_LAUNCH_TICKET_RE = re.compile(",
        '"requested_services": list(requested_profile.services)',
        '"requested_scopes": list(requested_profile.scopes)',
        "_canonical_custom_grant_scopes(scopes)",
        "GOOGLE_SCOPE_MAX_COUNT = 32",
        "GOOGLE_GRANT_SCOPE_MAX_COUNT = GOOGLE_SCOPE_MAX_COUNT + len(GOOGLE_IDENTITY_SCOPES)",
        "GOOGLE_SCOPE_TOTAL_MAX_LENGTH = 4096",
        "AUTHORIZATION_URL_MAX_LENGTH = 32 * 1024",
        "GOOGLE_LAUNCH_TICKET_MAX_LENGTH = 32 * 1024",
        "len(parsed.fragment) <= GOOGLE_LAUNCH_TICKET_MAX_LENGTH",
        '"button_sent": True',
        'platform_base_url=getattr(client, "base_url", None)',
        "parsed.hostname is not None",
        "platform_url.hostname is not None",
        "parsed.path == TINYHAT_GOOGLE_PREPARE_PATH",
        "GOOGLE_LAUNCH_TICKET_RE.fullmatch(parsed.fragment)",
        "profile=requested_profile",
        "_start_disconnect_intent(account_id=account_id)",
        "_start_disconnect_worker_process(",
        'f"{GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX}/{intent.intent_id}/activate"',
        'f"{GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX}/{intent.intent_id}/poll"',
        'f"{GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX}/{intent.intent_id}/claim"',
        'f"{GOOGLE_WORKSPACE_DISCONNECT_INTENTS_SUFFIX}/{intent.intent_id}/complete"',
        "GOOGLE_WORKSPACE_DISCONNECT_COMPLETION_RECEIPT_SCHEMA",
        "_write_disconnect_completion_receipt(",
        "_load_disconnect_completion_receipt(",
        "_resume_delete_pending_receipt(",
        "_retry_disconnect_completion(",
        "_sweep_expired_receiptless_disconnect_state(",
        "_resume_retained_disconnect_workers()",
        "record_completion_receipt=record_completion_receipt",
        "_wipe_invalid_credentials_and_pending_handoffs_locked()",
    )
    for phrase in required:
        require(phrase in text, f"google_workspace.py missing contract: {phrase}")
    forbidden = (
        '"authorization_url": authorization_url',
        "GOOGLE_REVOCATION_URI",
        "def _revoke_google_token",
        "def _disconnect_payload",
    )
    for phrase in forbidden:
        require(phrase not in text, f"google_workspace.py retained forbidden contract: {phrase}")

    app_text = (root / "google_workspace_app.py").read_text(encoding="utf-8")
    for phrase in (
        'APP_NAME = "gws"',
        "load_verified_google_workspace_credentials",
        "refresh_verified_google_workspace_credentials",
        '"GOOGLE_WORKSPACE_CLI_TOKEN": access_token',
        "AUDITED_ALLOWED_ROOT_COMMANDS_BY_GWS_VERSION",
        "root_command not in audited_allowed_commands",
        "verified_managed_gws_binary",
        "pass_fds=",
        "start_new_session=True",
        '"--page-all"',
        '"--output"',
        '"--upload"',
        '"--attach"',
        '"--sanitize"',
        '"content_is_untrusted": True',
    ):
        require(phrase in app_text, f"google_workspace_app.py missing contract: {phrase}")
    for phrase in (
        "oauth2.googleapis.com/token",
        "shutil.which",
        "shell=True",
        'Path.home() / ".local"',
        '"--draft"',
    ):
        require(
            phrase.lower() not in app_text.lower(),
            f"google_workspace_app.py retained forbidden contract: {phrase}",
        )

    manager_text = (root / "google_workspace_app_manager.py").read_text(encoding="utf-8")
    for phrase in (
        'PINNED_GWS_VERSION = "0.22.5"',
        '"de78ecdbd2f1a84cca0063a7ecbc440240fc14b6ebccbb17f4646b792a8c5c1f"',
        '"ab59c4bab4e7848740ba8cc3ef186152dab90121c45835b49bd1bf2a5c259b86"',
        '"94490295d9580e1e88574e715a0a162991747d12d62f8c7b8dcc8268b6c1cea0"',
        '"b68337faf1436fb2b3a287207cd57fef784a20fb4ab4f2429e51c4e0cfa0b50b"',
        '"9679052ece7c05ff3f05fb5f00c0437b460fade67631b60f279e445f5b5fd63e"',
        'BINARY_PATH = INSTALL_ROOT / "bin" / "gws"',
        "verified_managed_gws_binary",
        "tarfile.open",
        "_HttpsOnlyRedirectHandler",
        "_transactional_install",
        "managed_app_lock",
        "_sha256_open_file",
        'proc_path = f"/proc/self/fd/{source_fd}"',
        "_recover_interrupted_install",
        "partially_uninstalled",
    ):
        require(phrase in manager_text, f"google_workspace_app_manager.py missing: {phrase}")
    for phrase in (
        "subprocess",
        "shell=True",
        "npm install",
        "curl ",
        "memfd_create",
        "F_ADD_SEALS",
    ):
        require(
            phrase not in manager_text,
            f"google_workspace_app_manager.py retained forbidden contract: {phrase}",
        )


def main() -> int:
    root = repo_root()
    version = validate_versions(root)
    validate_hermes_adapter(root)
    validate_fresh_surface(root)
    validate_google_scope_manifest(root)
    validate_docs(root)
    validate_google_workspace_contract(root)
    print(f"framework-package: ok (version {version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
