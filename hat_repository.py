"""Bridge Hat repository work to the public Tinyhat Hermes runtime."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any


class HatRepositoryRuntimeError(RuntimeError):
    """The local runtime could not complete a Hat repository action."""


_CAMEL_CASE_BOUNDARY = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)
_NON_ALPHANUMERIC = re.compile(r"[^a-zA-Z0-9]+")
_CREDENTIAL_SEGMENTS = {
    "auth",
    "authorization",
    "bearer",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
}
_COMMON_RESULT_FIELDS = {
    "action",
    "hat_handle",
    "path",
    "repository",
    "schema",
}
_ACTION_REQUIRED_FIELDS = {
    "checkout": _COMMON_RESULT_FIELDS
    | {
        "branch",
        "created",
        "credential_persisted",
        "head_sha",
    },
    "status": _COMMON_RESULT_FIELDS | {"changed_paths", "clean", "head_sha"},
    "sync": _COMMON_RESULT_FIELDS
    | {"changed", "head_sha", "pushed", "synced_paths"},
    "reset": _COMMON_RESULT_FIELDS
    | {
        "credential_helper_removed",
        "local_clone_retained",
        "renewal_stopped",
        "residual_access_expires_at",
    },
}
_ACTION_OPTIONAL_FIELDS = {"sync": {"credential_persisted"}}


def _is_credential_field_name(key: object) -> bool:
    expanded = _CAMEL_CASE_BOUNDARY.sub("_", str(key))
    segments = tuple(
        segment.casefold()
        for segment in _NON_ALPHANUMERIC.split(expanded)
        if segment
    )
    if not segments:
        return False
    if segments in {
        ("credential", "helper", "removed"),
        ("credential", "persisted"),
    }:
        return False
    if _CREDENTIAL_SEGMENTS.intersection(segments):
        return True
    return any(
        pair in {("api", "key"), ("private", "key")}
        for pair in zip(segments, segments[1:])
    )


def _contains_credential_field(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            _is_credential_field_name(key) or _contains_credential_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_credential_field(item) for item in value)
    return False


def _matches_runtime_result_contract(result: dict[str, Any]) -> bool:
    action = result.get("action")
    if not isinstance(action, str) or action not in _ACTION_REQUIRED_FIELDS:
        return False
    required = _ACTION_REQUIRED_FIELDS[action]
    allowed = required | _ACTION_OPTIONAL_FIELDS.get(action, set())
    if not required.issubset(result) or not set(result).issubset(allowed):
        return False
    if result.get("schema") != "tinyhat_hat_repository_v1":
        return False
    if not all(
        isinstance(result.get(field), str) and bool(result[field])
        for field in ("hat_handle", "path")
    ):
        return False
    repository = result.get("repository")
    if not isinstance(repository, dict) or set(repository) != {"owner", "name"}:
        return False
    if not all(
        isinstance(repository.get(field), str) and bool(repository[field])
        for field in ("owner", "name")
    ):
        return False
    string_fields = {"branch", "head_sha"}
    boolean_fields = {
        "changed",
        "clean",
        "created",
        "credential_helper_removed",
        "local_clone_retained",
        "pushed",
        "renewal_stopped",
    }
    list_fields = {"changed_paths", "synced_paths"}
    if any(
        field in result and not isinstance(result[field], str)
        for field in string_fields
    ):
        return False
    if any(
        field in result and not isinstance(result[field], bool)
        for field in boolean_fields
    ):
        return False
    if any(
        field in result
        and (
            not isinstance(result[field], list)
            or not all(isinstance(item, str) for item in result[field])
        )
        for field in list_fields
    ):
        return False
    if "credential_persisted" in result and result["credential_persisted"] is not False:
        return False
    residual_expiry = result.get("residual_access_expires_at")
    if action == "reset" and residual_expiry is not None and not isinstance(
        residual_expiry, str
    ):
        return False
    return True


def run_hat_repository(
    payload: dict[str, Any], *, timeout_seconds: int = 180
) -> dict[str, Any]:
    """Run the token-safe local Git workflow without returning a credential."""

    runtime_prefix = (
        os.getenv("TINYHAT_RUNTIME_PREFIX") or "/opt/tinyhat-hermes-runtime"
    ).strip()
    env = dict(os.environ)
    existing_python_path = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = (
        f"{runtime_prefix}:{existing_python_path}"
        if existing_python_path
        else runtime_prefix
    )
    try:
        process = subprocess.run(
            [sys.executable, "-m", "hermes_runtime.hat_repository_cli"],
            input=json.dumps(payload, separators=(",", ":")),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HatRepositoryRuntimeError(
            "The Tinyhat runtime repository helper is unavailable."
        ) from exc
    try:
        result = json.loads(process.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise HatRepositoryRuntimeError(
            "The Tinyhat runtime repository helper returned invalid output."
        ) from exc
    if not isinstance(result, dict):
        raise HatRepositoryRuntimeError(
            "The Tinyhat runtime repository helper returned invalid output."
        )
    if process.returncode != 0 or result.get("status") == "error":
        message = str(result.get("message") or "").strip()
        raise HatRepositoryRuntimeError(
            message or "The Hat repository operation failed."
        )
    requested_action = str(payload.get("action") or "").strip().casefold()
    if result.get("action") != requested_action:
        raise HatRepositoryRuntimeError(
            "The runtime returned a mismatched repository action."
        )
    # The runtime contract is value-blind. Fail closed if a future runtime
    # accidentally puts a credential-shaped field in plugin-visible output.
    if _contains_credential_field(result) or not _matches_runtime_result_contract(
        result
    ):
        raise HatRepositoryRuntimeError(
            "The runtime returned unsafe repository helper output."
        )
    return result


__all__ = ["HatRepositoryRuntimeError", "run_hat_repository"]
