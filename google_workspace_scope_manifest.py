"""Load and resolve Tinyhat's public Google Workspace OAuth scope manifest."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

MANIFEST_PATH = Path(__file__).with_name("google_workspace_scope_manifest.json")
MANIFEST_SCHEMA = "tinyhat_google_workspace_scope_manifest_v1"
_EXPECTED_IDENTITY_BUNDLE_ID = "google_workspace_identity_v1"
CUSTOM_BUNDLE_ID = "google_workspace_custom_v1"
DEFAULT_CLIENT_POLICY_ID = "tinyhat-production"
MAX_SAVED_SCOPE_LENGTH = 512
MIN_VISIBLE_ASCII_CODEPOINT = 0x21
_EXACT_LEGACY_SCOPE_URLS = frozenset(
    {
        "https://mail.google.com/",
        "https://www.google.com/calendar/feeds",
        "https://www.google.com/m8/feeds",
    }
)

_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_VERSION_RE = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
_CLASSIFICATIONS = frozenset({"non_sensitive", "sensitive", "restricted"})
_CLASSIFICATION_PRIORITY = {"non_sensitive": 0, "sensitive": 1, "restricted": 2}
_ACCESS_MODES = frozenset({"read", "write"})
_REQUEST_STATES = frozenset({"approved", "review_required", "legacy_only"})
_SCOPE_KEYS = frozenset(
    {
        "id",
        "canonical_url",
        "aliases",
        "service",
        "display_name",
        "classification",
        "access_mode",
        "read_only",
        "enabled_api",
        "implemented_feature",
        "capabilities",
        "operations",
        "data_read",
        "data_written",
        "narrower_alternatives",
        "why_narrower_insufficient",
        "user_copy",
        "demo_steps",
        "verification_status",
        "supersedes",
        "client_states",
    }
)
_PRESET_KEYS = frozenset(
    {
        "id",
        "display_name",
        "capability_bundle",
        "scope_ids",
        "user_copy",
        "risk_class",
        "recommended",
        "default",
        "read_only",
    }
)
_CLIENT_POLICY_KEYS = frozenset(
    {
        "id",
        "display_name",
        "environment",
        "allowed_request_states",
        "allowed_verification_states",
        "user_copy",
    }
)
_LEGACY_BUNDLE_KEYS = frozenset(
    {"id", "profile_ids", "scope_source", "scope_ids", "requestable", "description"}
)
_COMPATIBILITY_SCOPE_DISCLOSURE_KEYS = frozenset(
    {"canonical_url", "service", "status", "user_copy", "rationale"}
)
_EXPECTED_PRESETS = {
    "workspace_reader": (
        ("gmail.readonly", "calendar.events.readonly", "drive.readonly"),
        "restricted",
        True,
        False,
    ),
    "mail_writer": (("gmail.compose",), "restricted", True, False),
    "inbox_manager": (("gmail.modify",), "restricted", True, False),
    "calendar_coordinator": (("calendar.events",), "sensitive", True, False),
    "file_collaborator": (("drive.file",), "non_sensitive", True, False),
}
_EXPECTED_POLICIES = frozenset({"tinyhat-development", "tinyhat-production"})
_EXPECTED_LEGACY_BUNDLES = frozenset(
    {
        "google_workspace_recommended_v1",
        "google_workspace_readonly_v1",
        "google_workspace_gmail_send_v1",
        "google_workspace_calendar_write_v1",
        "google_workspace_gmail_send_calendar_write_v1",
        "google_workspace_custom_v1",
    }
)


@dataclass(frozen=True)
class BlockedScope:
    """One requested scope that cannot be sent to the selected OAuth client."""

    scope_url: str
    scope_id: str | None
    display_name: str
    request_state: str
    verification_state: str
    reason: str


@dataclass(frozen=True)
class ScopeResolution:
    """Deterministic manifest resolution for a preset/custom scope request."""

    scope_urls: tuple[str, ...]
    services: tuple[str, ...]
    capabilities: tuple[str, ...]
    scope_labels: tuple[str, ...]
    selected_preset_ids: tuple[str, ...]
    approved: bool
    blocked: tuple[BlockedScope, ...]
    access_label: str
    read_only: bool
    bundle_id: str


def _fail(location: str, message: str) -> None:
    raise ValueError(f"Invalid Google Workspace scope manifest at {location}: {message}")


def _mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _fail(location, "expected an object")
    return value


def _sequence(value: object, location: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(location, "expected an array")
    return value


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], location: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        _fail(location, f"keys differ; missing={missing}, extra={extra}")


def _string(value: object, location: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        _fail(location, "expected a non-empty string")
    return value


def _boolean(value: object, location: str) -> bool:
    if not isinstance(value, bool):
        _fail(location, "expected a boolean")
    return value


def _strings(
    value: object,
    location: str,
    *,
    allow_empty: bool = True,
    unique: bool = True,
) -> tuple[str, ...]:
    rows = _sequence(value, location)
    result = tuple(_string(item, f"{location}[{index}]") for index, item in enumerate(rows))
    if not allow_empty and not result:
        _fail(location, "must not be empty")
    if unique and len(result) != len(set(result)):
        _fail(location, "must not contain duplicates")
    return result


def _id(value: object, location: str) -> str:
    result = _string(value, location)
    if not _ID_RE.fullmatch(result):
        _fail(location, "must be a stable lowercase id")
    return result


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _validate_manifest(  # noqa: PLR0912, PLR0915
    raw: Mapping[str, Any],
) -> None:
    _exact_keys(
        raw,
        frozenset(
            {
                "schema",
                "manifest_version",
                "identity_capability_bundle",
                "identity_scope_ids",
                "custom_scope_policy",
                "compatibility_scope_disclosures",
                "client_policies",
                "scopes",
                "presets",
                "legacy_bundles",
            }
        ),
        "$",
    )
    if raw["schema"] != MANIFEST_SCHEMA:
        _fail("$.schema", f"expected {MANIFEST_SCHEMA!r}")
    version = _string(raw["manifest_version"], "$.manifest_version")
    if not _VERSION_RE.fullmatch(version):
        _fail("$.manifest_version", "expected semantic version MAJOR.MINOR.PATCH")
    identity_bundle_id = _id(raw["identity_capability_bundle"], "$.identity_capability_bundle")
    if identity_bundle_id != _EXPECTED_IDENTITY_BUNDLE_ID:
        _fail(
            "$.identity_capability_bundle",
            f"expected {_EXPECTED_IDENTITY_BUNDLE_ID!r}",
        )

    identity_scope_ids = _strings(
        raw["identity_scope_ids"], "$.identity_scope_ids", allow_empty=False
    )
    if identity_scope_ids != ("openid", "email", "profile"):
        _fail("$.identity_scope_ids", "must be exactly openid, email, profile in that order")

    custom_policy = _mapping(raw["custom_scope_policy"], "$.custom_scope_policy")
    _exact_keys(
        custom_policy,
        frozenset(
            {
                "canonical_url_prefix",
                "unknown_scope_request_state",
                "unknown_scope_verification_state",
                "user_copy",
            }
        ),
        "$.custom_scope_policy",
    )
    prefix = _string(
        custom_policy["canonical_url_prefix"],
        "$.custom_scope_policy.canonical_url_prefix",
    )
    if prefix != "https://www.googleapis.com/auth/":
        _fail("$.custom_scope_policy.canonical_url_prefix", "unexpected Google scope prefix")
    if custom_policy["unknown_scope_request_state"] != "review_required":
        _fail("$.custom_scope_policy.unknown_scope_request_state", "must be review_required")
    _string(
        custom_policy["unknown_scope_verification_state"],
        "$.custom_scope_policy.unknown_scope_verification_state",
    )
    _string(custom_policy["user_copy"], "$.custom_scope_policy.user_copy")

    compatibility_scope_urls: list[str] = []
    for index, item in enumerate(
        _sequence(
            raw["compatibility_scope_disclosures"],
            "$.compatibility_scope_disclosures",
        )
    ):
        location = f"$.compatibility_scope_disclosures[{index}]"
        disclosure = _mapping(item, location)
        _exact_keys(disclosure, _COMPATIBILITY_SCOPE_DISCLOSURE_KEYS, location)
        canonical_url = _string(disclosure["canonical_url"], f"{location}.canonical_url")
        if canonical_url not in _EXACT_LEGACY_SCOPE_URLS and (
            not canonical_url.startswith(prefix) or canonical_url == prefix
        ):
            _fail(
                f"{location}.canonical_url",
                "must be a canonical Google API scope URL or an exact supported legacy scope",
            )
        compatibility_scope_urls.append(canonical_url)
        _id(disclosure["service"], f"{location}.service")
        if disclosure["status"] != "historical_disclosure_only":
            _fail(f"{location}.status", "must be historical_disclosure_only")
        _string(disclosure["user_copy"], f"{location}.user_copy")
        _string(disclosure["rationale"], f"{location}.rationale")
    if len(compatibility_scope_urls) != len(set(compatibility_scope_urls)):
        _fail(
            "$.compatibility_scope_disclosures",
            "canonical scope URLs must be unique",
        )
    if not set(compatibility_scope_urls) >= _EXACT_LEGACY_SCOPE_URLS:
        _fail(
            "$.compatibility_scope_disclosures",
            "must declare every exact supported legacy scope",
        )

    policy_ids: list[str] = []
    for index, item in enumerate(_sequence(raw["client_policies"], "$.client_policies")):
        location = f"$.client_policies[{index}]"
        policy = _mapping(item, location)
        _exact_keys(policy, _CLIENT_POLICY_KEYS, location)
        policy_id = _id(policy["id"], f"{location}.id")
        policy_ids.append(policy_id)
        _string(policy["display_name"], f"{location}.display_name")
        environment = _string(policy["environment"], f"{location}.environment")
        if environment not in {"development", "production"}:
            _fail(f"{location}.environment", "must be development or production")
        allowed = _strings(
            policy["allowed_request_states"],
            f"{location}.allowed_request_states",
            allow_empty=False,
        )
        if any(state not in _REQUEST_STATES for state in allowed):
            _fail(f"{location}.allowed_request_states", "contains an unknown request state")
        _strings(
            policy["allowed_verification_states"],
            f"{location}.allowed_verification_states",
            allow_empty=False,
        )
        _string(policy["user_copy"], f"{location}.user_copy")
    if len(policy_ids) != len(set(policy_ids)):
        _fail("$.client_policies", "client policy ids must be unique")
    if frozenset(policy_ids) != _EXPECTED_POLICIES:
        _fail("$.client_policies", f"must define exactly {sorted(_EXPECTED_POLICIES)}")

    scope_ids: list[str] = []
    canonical_urls: list[str] = []
    aliases: list[str] = []
    scope_rows = _sequence(raw["scopes"], "$.scopes")
    for index, item in enumerate(scope_rows):
        location = f"$.scopes[{index}]"
        scope = _mapping(item, location)
        _exact_keys(scope, _SCOPE_KEYS, location)
        scope_id = _id(scope["id"], f"{location}.id")
        scope_ids.append(scope_id)
        canonical = _string(scope["canonical_url"], f"{location}.canonical_url")
        if scope_id in identity_scope_ids:
            if canonical != scope_id:
                _fail(f"{location}.canonical_url", "identity scope URL must equal its id")
        elif not canonical.startswith(prefix) or canonical == prefix:
            _fail(f"{location}.canonical_url", "must be a canonical Google API scope URL")
        canonical_urls.append(canonical)
        scope_aliases = _strings(scope["aliases"], f"{location}.aliases")
        if any(not alias.startswith(prefix) or alias == prefix for alias in scope_aliases):
            _fail(f"{location}.aliases", "aliases must be canonical Google API scope URLs")
        aliases.extend(scope_aliases)
        _id(scope["service"], f"{location}.service")
        for key in (
            "display_name",
            "enabled_api",
            "implemented_feature",
            "user_copy",
            "why_narrower_insufficient",
            "verification_status",
        ):
            _string(scope[key], f"{location}.{key}")
        classification = _string(scope["classification"], f"{location}.classification")
        if classification not in _CLASSIFICATIONS:
            _fail(f"{location}.classification", "unknown Google scope classification")
        access_mode = _string(scope["access_mode"], f"{location}.access_mode")
        if access_mode not in _ACCESS_MODES:
            _fail(f"{location}.access_mode", "must be read or write")
        read_only = _boolean(scope["read_only"], f"{location}.read_only")
        if read_only != (access_mode == "read"):
            _fail(f"{location}.read_only", "must agree with access_mode")
        _strings(scope["capabilities"], f"{location}.capabilities", allow_empty=False)
        _strings(scope["operations"], f"{location}.operations", allow_empty=False)
        _strings(scope["data_read"], f"{location}.data_read")
        _strings(scope["data_written"], f"{location}.data_written")
        _strings(scope["narrower_alternatives"], f"{location}.narrower_alternatives")
        _strings(scope["demo_steps"], f"{location}.demo_steps", allow_empty=False)
        _strings(scope["supersedes"], f"{location}.supersedes")
        client_states = _mapping(scope["client_states"], f"{location}.client_states")
        if frozenset(client_states) != _EXPECTED_POLICIES:
            _fail(f"{location}.client_states", "must define every client policy exactly once")
        for policy_id, state_item in client_states.items():
            state_location = f"{location}.client_states.{policy_id}"
            state = _mapping(state_item, state_location)
            _exact_keys(
                state,
                frozenset({"request_state", "verification_state"}),
                state_location,
            )
            request_state = _string(state["request_state"], f"{state_location}.request_state")
            if request_state not in _REQUEST_STATES:
                _fail(f"{state_location}.request_state", "unknown request state")
            verification_state = _string(
                state["verification_state"], f"{state_location}.verification_state"
            )
            policy = next(
                item
                for item in _sequence(raw["client_policies"], "$.client_policies")
                if _mapping(item, "$.client_policies[]")["id"] == policy_id
            )
            allowed_request_states = set(
                _strings(
                    _mapping(policy, "$.client_policies[]")["allowed_request_states"],
                    "$.client_policies[].allowed_request_states",
                    allow_empty=False,
                )
            )
            allowed_verification_states = set(
                _strings(
                    _mapping(policy, "$.client_policies[]")["allowed_verification_states"],
                    "$.client_policies[].allowed_verification_states",
                    allow_empty=False,
                )
            )
            if (
                request_state in allowed_request_states
                and verification_state not in allowed_verification_states
            ):
                _fail(
                    state_location,
                    "an approved request must have a verification state allowed "
                    "by its client policy",
                )
    if len(scope_ids) != len(set(scope_ids)):
        _fail("$.scopes", "scope ids must be unique")
    if len(canonical_urls) != len(set(canonical_urls)):
        _fail("$.scopes", "canonical scope URLs must be unique")
    if len(aliases) != len(set(aliases)) or set(aliases) & set(canonical_urls):
        _fail("$.scopes", "aliases must be unique and must not duplicate canonical URLs")
    if set(compatibility_scope_urls) & (set(canonical_urls) | set(aliases)):
        _fail(
            "$.compatibility_scope_disclosures",
            "disclosure-only scope URLs cannot also be implemented scope URLs or aliases",
        )
    scope_id_set = set(scope_ids)
    if not set(identity_scope_ids) <= scope_id_set:
        _fail("$.identity_scope_ids", "identity scopes must exist in scopes")
    scope_by_id = {
        str(_mapping(item, "$.scopes[]")["id"]): _mapping(item, "$.scopes[]") for item in scope_rows
    }
    for scope_id, scope in scope_by_id.items():
        for key in ("narrower_alternatives", "supersedes"):
            references = _strings(scope[key], f"$.scopes[{scope_id}].{key}")
            unknown = sorted(set(references) - scope_id_set)
            if unknown:
                _fail(f"$.scopes[{scope_id}].{key}", f"unknown scope ids {unknown}")
            if scope_id in references:
                _fail(f"$.scopes[{scope_id}].{key}", "a scope cannot reference itself")
    _validate_supersession_cycles(scope_by_id)

    preset_ids: list[str] = []
    bundles: list[str] = []
    for index, item in enumerate(_sequence(raw["presets"], "$.presets")):
        location = f"$.presets[{index}]"
        preset = _mapping(item, location)
        _exact_keys(preset, _PRESET_KEYS, location)
        preset_id = _id(preset["id"], f"{location}.id")
        preset_ids.append(preset_id)
        _string(preset["display_name"], f"{location}.display_name")
        bundles.append(_id(preset["capability_bundle"], f"{location}.capability_bundle"))
        preset_scope_ids = _strings(preset["scope_ids"], f"{location}.scope_ids", allow_empty=False)
        if set(preset_scope_ids) - scope_id_set:
            _fail(f"{location}.scope_ids", "contains unknown scope ids")
        _string(preset["user_copy"], f"{location}.user_copy")
        risk_class = _string(preset["risk_class"], f"{location}.risk_class")
        if risk_class not in _CLASSIFICATIONS:
            _fail(f"{location}.risk_class", "must be a known Google classification")
        computed_risk_class = max(
            (str(scope_by_id[item]["classification"]) for item in preset_scope_ids),
            key=_CLASSIFICATION_PRIORITY.__getitem__,
        )
        if risk_class != computed_risk_class:
            _fail(f"{location}.risk_class", "must equal the highest-risk member scope")
        recommended = _boolean(preset["recommended"], f"{location}.recommended")
        default = _boolean(preset["default"], f"{location}.default")
        declared_read_only = _boolean(preset["read_only"], f"{location}.read_only")
        computed_read_only = all(bool(scope_by_id[item]["read_only"]) for item in preset_scope_ids)
        if declared_read_only != computed_read_only:
            _fail(f"{location}.read_only", "must agree with member scopes")
        expected = _EXPECTED_PRESETS.get(preset_id)
        if expected is None:
            _fail(location, "does not match the required preset contract")
        expected_scope_ids, expected_risk, expected_recommended, expected_default = expected
        if preset_scope_ids != expected_scope_ids:
            _fail(f"{location}.scope_ids", "does not match the required preset contract")
        if (risk_class, recommended, default) != (
            expected_risk,
            expected_recommended,
            expected_default,
        ):
            _fail(location, "risk, recommendation, or default status drifted")
    if set(preset_ids) != set(_EXPECTED_PRESETS) or len(preset_ids) != len(set(preset_ids)):
        _fail("$.presets", "must define the five required preset ids exactly once")
    if len(bundles) != len(set(bundles)):
        _fail("$.presets", "capability bundle ids must be unique")

    legacy_ids: list[str] = []
    profile_ids: list[str] = []
    for index, item in enumerate(_sequence(raw["legacy_bundles"], "$.legacy_bundles")):
        location = f"$.legacy_bundles[{index}]"
        bundle = _mapping(item, location)
        _exact_keys(bundle, _LEGACY_BUNDLE_KEYS, location)
        legacy_ids.append(_id(bundle["id"], f"{location}.id"))
        profile_ids.extend(_strings(bundle["profile_ids"], f"{location}.profile_ids"))
        source = _string(bundle["scope_source"], f"{location}.scope_source")
        if source not in {"fixed", "saved_grant"}:
            _fail(f"{location}.scope_source", "must be fixed or saved_grant")
        legacy_scope_ids = _strings(bundle["scope_ids"], f"{location}.scope_ids")
        if set(legacy_scope_ids) - scope_id_set:
            _fail(f"{location}.scope_ids", "contains unknown scope ids")
        if source == "fixed" and not legacy_scope_ids:
            _fail(f"{location}.scope_ids", "fixed bundles must contain scopes")
        if source == "saved_grant" and legacy_scope_ids:
            _fail(f"{location}.scope_ids", "saved-grant bundles must not fix scopes")
        if _boolean(bundle["requestable"], f"{location}.requestable"):
            _fail(f"{location}.requestable", "legacy bundles cannot launch new requests")
        _string(bundle["description"], f"{location}.description")
    if frozenset(legacy_ids) != _EXPECTED_LEGACY_BUNDLES or len(legacy_ids) != len(set(legacy_ids)):
        _fail("$.legacy_bundles", "must define all compatibility bundle ids exactly once")
    if len(profile_ids) != len(set(profile_ids)):
        _fail("$.legacy_bundles", "legacy profile ids must be unique")


def _validate_supersession_cycles(scope_by_id: Mapping[str, Mapping[str, Any]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(scope_id: str) -> None:
        if scope_id in visiting:
            _fail("$.scopes", f"supersession cycle includes {scope_id}")
        if scope_id in visited:
            return
        visiting.add(scope_id)
        for child in _strings(scope_by_id[scope_id]["supersedes"], "$.scopes[].supersedes"):
            visit(child)
        visiting.remove(scope_id)
        visited.add(scope_id)

    for scope_id in scope_by_id:
        visit(scope_id)


def load_manifest(path: str | Path | None = None) -> Mapping[str, Any]:
    """Load, strictly validate, and recursively freeze a manifest."""

    manifest_path = Path(path) if path is not None else MANIFEST_PATH
    try:
        with manifest_path.open("r", encoding="utf-8") as manifest_file:
            raw = json.load(manifest_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load Google Workspace scope manifest: {exc}") from exc
    root = _mapping(raw, "$")
    _validate_manifest(root)
    return _freeze(root)


MANIFEST = load_manifest()
IDENTITY_BUNDLE_ID = str(MANIFEST["identity_capability_bundle"])
COMPATIBILITY_SCOPE_DISCLOSURES_BY_URL = MappingProxyType(
    {
        str(disclosure["canonical_url"]): disclosure
        for disclosure in MANIFEST["compatibility_scope_disclosures"]
    }
)
HISTORICAL_CANONICAL_SCOPE_URLS = frozenset(COMPATIBILITY_SCOPE_DISCLOSURES_BY_URL)
SCOPES_BY_ID = MappingProxyType({str(scope["id"]): scope for scope in MANIFEST["scopes"]})
SCOPES_BY_URL = MappingProxyType(
    {str(scope["canonical_url"]): scope for scope in MANIFEST["scopes"]}
)
ALIASES_TO_SCOPE_URL = MappingProxyType(
    {
        str(alias): str(scope["canonical_url"])
        for scope in MANIFEST["scopes"]
        for alias in scope["aliases"]
    }
)
PRESETS_BY_ID = MappingProxyType({str(preset["id"]): preset for preset in MANIFEST["presets"]})
CLIENT_POLICIES_BY_ID = MappingProxyType(
    {str(policy["id"]): policy for policy in MANIFEST["client_policies"]}
)
LEGACY_BUNDLES_BY_ID = MappingProxyType(
    {str(bundle["id"]): bundle for bundle in MANIFEST["legacy_bundles"]}
)
LEGACY_PROFILE_TO_BUNDLE_ID = MappingProxyType(
    {
        str(profile_id): str(bundle["id"])
        for bundle in MANIFEST["legacy_bundles"]
        for profile_id in bundle["profile_ids"]
    }
)
IDENTITY_SCOPE_IDS = tuple(str(item) for item in MANIFEST["identity_scope_ids"])
IDENTITY_SCOPE_URLS = tuple(
    str(SCOPES_BY_ID[scope_id]["canonical_url"]) for scope_id in IDENTITY_SCOPE_IDS
)
SCOPE_ORDER = tuple(str(scope["canonical_url"]) for scope in MANIFEST["scopes"])
PRESET_ORDER = tuple(str(preset["id"]) for preset in MANIFEST["presets"])
CANONICAL_GOOGLE_SCOPE_PREFIX = str(MANIFEST["custom_scope_policy"]["canonical_url_prefix"])


def get_preset(preset_id: str) -> Mapping[str, Any]:
    """Return one immutable preset record or raise a clear input error."""

    try:
        return PRESETS_BY_ID[preset_id]
    except KeyError as exc:
        raise ValueError(f"Unknown Google Workspace preset: {preset_id}") from exc


def get_legacy_bundle(bundle_id: str) -> Mapping[str, Any]:
    """Return one immutable historical bundle record."""

    try:
        return LEGACY_BUNDLES_BY_ID[bundle_id]
    except KeyError as exc:
        raise ValueError(f"Unknown historical Google Workspace bundle: {bundle_id}") from exc


def legacy_bundle_for_profile(profile_id: str) -> Mapping[str, Any]:
    """Resolve a historical profile name without changing its saved meaning."""

    try:
        bundle_id = LEGACY_PROFILE_TO_BUNDLE_ID[profile_id]
    except KeyError as exc:
        raise ValueError(f"Unknown historical Google Workspace profile: {profile_id}") from exc
    return LEGACY_BUNDLES_BY_ID[bundle_id]


def legacy_scope_urls(
    bundle_id: str,
    *,
    saved_scope_urls: Iterable[str] = (),
) -> tuple[str, ...]:
    """Reconstruct exact historical scopes, including saved custom grants."""

    bundle = get_legacy_bundle(bundle_id)
    if bundle["scope_source"] == "saved_grant":
        scopes = tuple(_saved_scope_value(item) for item in saved_scope_urls)
        if not scopes:
            raise ValueError("A saved-grant legacy bundle requires saved_scope_urls")
        return _dedupe(scopes)
    if tuple(saved_scope_urls):
        raise ValueError("saved_scope_urls are only valid for a saved-grant legacy bundle")
    return tuple(
        str(SCOPES_BY_ID[str(scope_id)]["canonical_url"]) for scope_id in bundle["scope_ids"]
    )


def _saved_scope_value(scope_url: object) -> str:
    """Validate without rewriting an already-issued historical grant."""

    if not isinstance(scope_url, str):
        raise ValueError("Saved Google OAuth scope values must be strings")
    if (
        not scope_url
        or len(scope_url) > MAX_SAVED_SCOPE_LENGTH
        or not scope_url.isascii()
        or any(
            character.isspace() or ord(character) < MIN_VISIBLE_ASCII_CODEPOINT
            for character in scope_url
        )
    ):
        raise ValueError(f"Invalid saved Google OAuth scope: {scope_url!r}")
    return scope_url


def _canonicalize_scope_url(scope_url: object) -> str:
    if not isinstance(scope_url, str):
        raise ValueError("Google OAuth scope values must be strings")
    value = scope_url.strip()
    if value != scope_url or not value or not value.isascii():
        raise ValueError(f"Invalid canonical Google OAuth scope: {scope_url!r}")
    value = ALIASES_TO_SCOPE_URL.get(value, value)
    if value in IDENTITY_SCOPE_URLS:
        return value
    if value in HISTORICAL_CANONICAL_SCOPE_URLS:
        return value
    if not value.startswith(CANONICAL_GOOGLE_SCOPE_PREFIX):
        raise ValueError(f"Invalid canonical Google OAuth scope: {scope_url!r}")
    suffix = value[len(CANONICAL_GOOGLE_SCOPE_PREFIX) :]
    if not suffix or any(
        character.isspace() or ord(character) < MIN_VISIBLE_ASCII_CODEPOINT for character in suffix
    ):
        raise ValueError(f"Invalid canonical Google OAuth scope: {scope_url!r}")
    return value


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _transitively_superseded_scope_urls(selected: set[str]) -> set[str]:
    """Return the complete supersession closure for the selected scopes."""

    pending = [
        str(scope["id"])
        for scope_url in selected
        if (scope := SCOPES_BY_URL.get(scope_url)) is not None
    ]
    visited = set(pending)
    superseded_ids: set[str] = set()
    while pending:
        scope_id = pending.pop()
        for child_value in SCOPES_BY_ID[scope_id]["supersedes"]:
            child_id = str(child_value)
            superseded_ids.add(child_id)
            if child_id not in visited:
                visited.add(child_id)
                pending.append(child_id)
    return {str(SCOPES_BY_ID[scope_id]["canonical_url"]) for scope_id in superseded_ids}


def normalize_scope_urls(scope_urls: Iterable[str]) -> tuple[str, ...]:
    """Canonicalize, add identity, remove superseded scopes, and order deterministically."""

    selected = set(IDENTITY_SCOPE_URLS)
    selected.update(_canonicalize_scope_url(scope_url) for scope_url in scope_urls)
    selected.difference_update(_transitively_superseded_scope_urls(selected))
    ordered_known = [scope_url for scope_url in SCOPE_ORDER if scope_url in selected]
    unknown = sorted(selected - set(SCOPE_ORDER))
    return tuple(ordered_known + unknown)


def preset_scope_urls(preset_ids: Iterable[str]) -> tuple[str, ...]:
    """Return the exact manifest scope union for one or more presets."""

    selected = set(preset_ids)
    unknown = sorted(selected - set(PRESETS_BY_ID))
    if unknown:
        raise ValueError(f"Unknown Google Workspace presets: {', '.join(unknown)}")
    scope_urls: list[str] = []
    for preset_id in PRESET_ORDER:
        if preset_id not in selected:
            continue
        scope_urls.extend(
            str(SCOPES_BY_ID[str(scope_id)]["canonical_url"])
            for scope_id in PRESETS_BY_ID[preset_id]["scope_ids"]
        )
    return normalize_scope_urls(scope_urls)


def blocked_scope_details(
    scope_urls: Iterable[str],
    *,
    client_policy_id: str = DEFAULT_CLIENT_POLICY_ID,
) -> tuple[BlockedScope, ...]:
    """Explain scopes that the selected OAuth client may not request."""

    if client_policy_id not in CLIENT_POLICIES_BY_ID:
        raise ValueError(f"Unknown Google OAuth client policy: {client_policy_id}")
    policy = CLIENT_POLICIES_BY_ID[client_policy_id]
    allowed_states = set(str(item) for item in policy["allowed_request_states"])
    unknown_request_state = str(MANIFEST["custom_scope_policy"]["unknown_scope_request_state"])
    unknown_verification_state = str(
        MANIFEST["custom_scope_policy"]["unknown_scope_verification_state"]
    )
    blocked: list[BlockedScope] = []
    for scope_url in normalize_scope_urls(scope_urls):
        scope = SCOPES_BY_URL.get(scope_url)
        if scope is None:
            blocked.append(
                BlockedScope(
                    scope_url=scope_url,
                    scope_id=None,
                    display_name=scope_url,
                    request_state=unknown_request_state,
                    verification_state=unknown_verification_state,
                    reason="This canonical Google scope is not listed in the public manifest.",
                )
            )
            continue
        client_state = scope["client_states"][client_policy_id]
        request_state = str(client_state["request_state"])
        if request_state in allowed_states:
            continue
        blocked.append(
            BlockedScope(
                scope_url=scope_url,
                scope_id=str(scope["id"]),
                display_name=str(scope["display_name"]),
                request_state=request_state,
                verification_state=str(client_state["verification_state"]),
                reason=str(scope["user_copy"]),
            )
        )
    return tuple(blocked)


def resolve_scope_request(  # noqa: PLR0912
    *,
    preset_ids: Iterable[str] = (),
    scope_urls: Iterable[str] = (),
    client_policy_id: str = DEFAULT_CLIENT_POLICY_ID,
) -> ScopeResolution:
    """Resolve a composable preset/custom request against one client policy."""

    requested_preset_ids = set(preset_ids)
    unknown_presets = sorted(requested_preset_ids - set(PRESETS_BY_ID))
    if unknown_presets:
        raise ValueError(f"Unknown Google Workspace presets: {', '.join(unknown_presets)}")
    selected_preset_ids = tuple(
        preset_id for preset_id in PRESET_ORDER if preset_id in requested_preset_ids
    )
    explicit_scope_urls = tuple(scope_urls)
    combined: list[str] = []
    for preset_id in selected_preset_ids:
        combined.extend(
            str(SCOPES_BY_ID[str(scope_id)]["canonical_url"])
            for scope_id in PRESETS_BY_ID[preset_id]["scope_ids"]
        )
    combined.extend(explicit_scope_urls)
    normalized = normalize_scope_urls(combined)
    blocked = blocked_scope_details(normalized, client_policy_id=client_policy_id)

    services: list[str] = []
    capabilities: list[str] = []
    labels: list[str] = []
    read_only = True
    for scope_url in normalized:
        scope = SCOPES_BY_URL.get(scope_url)
        if scope is None:
            if "google" not in services:
                services.append("google")
            read_only = False
            continue
        service = str(scope["service"])
        if service not in services:
            services.append(service)
        for capability in scope["capabilities"]:
            capability_value = str(capability)
            if capability_value not in capabilities:
                capabilities.append(capability_value)
        label = str(scope["display_name"])
        if label not in labels:
            labels.append(label)
        if not bool(scope["read_only"]):
            read_only = False

    if not selected_preset_ids and not explicit_scope_urls:
        bundle_id = IDENTITY_BUNDLE_ID
        access_label = "Identity only"
    elif len(selected_preset_ids) == 1 and not explicit_scope_urls:
        preset = PRESETS_BY_ID[selected_preset_ids[0]]
        bundle_id = str(preset["capability_bundle"])
        access_label = str(preset["display_name"])
    else:
        bundle_id = CUSTOM_BUNDLE_ID
        access_label = "Custom Google access"

    return ScopeResolution(
        scope_urls=normalized,
        services=tuple(services),
        capabilities=tuple(capabilities),
        scope_labels=tuple(labels),
        selected_preset_ids=selected_preset_ids,
        approved=not blocked,
        blocked=blocked,
        access_label=access_label,
        read_only=read_only,
        bundle_id=bundle_id,
    )


def approved_scope_urls(
    client_policy_id: str = DEFAULT_CLIENT_POLICY_ID,
) -> tuple[str, ...]:
    """Return every manifest-listed scope requestable for the selected client."""

    if client_policy_id not in CLIENT_POLICIES_BY_ID:
        raise ValueError(f"Unknown Google OAuth client policy: {client_policy_id}")
    policy = CLIENT_POLICIES_BY_ID[client_policy_id]
    allowed_states = set(str(item) for item in policy["allowed_request_states"])
    return tuple(
        scope_url
        for scope_url in SCOPE_ORDER
        if str(SCOPES_BY_URL[scope_url]["client_states"][client_policy_id]["request_state"])
        in allowed_states
    )


__all__ = [
    "ALIASES_TO_SCOPE_URL",
    "CANONICAL_GOOGLE_SCOPE_PREFIX",
    "CLIENT_POLICIES_BY_ID",
    "COMPATIBILITY_SCOPE_DISCLOSURES_BY_URL",
    "CUSTOM_BUNDLE_ID",
    "DEFAULT_CLIENT_POLICY_ID",
    "HISTORICAL_CANONICAL_SCOPE_URLS",
    "IDENTITY_BUNDLE_ID",
    "IDENTITY_SCOPE_IDS",
    "IDENTITY_SCOPE_URLS",
    "LEGACY_BUNDLES_BY_ID",
    "LEGACY_PROFILE_TO_BUNDLE_ID",
    "MANIFEST",
    "MANIFEST_PATH",
    "MANIFEST_SCHEMA",
    "PRESETS_BY_ID",
    "PRESET_ORDER",
    "SCOPES_BY_ID",
    "SCOPES_BY_URL",
    "SCOPE_ORDER",
    "BlockedScope",
    "ScopeResolution",
    "approved_scope_urls",
    "blocked_scope_details",
    "get_legacy_bundle",
    "get_preset",
    "legacy_bundle_for_profile",
    "legacy_scope_urls",
    "load_manifest",
    "normalize_scope_urls",
    "preset_scope_urls",
    "resolve_scope_request",
]
