"""Bridge Hat repository work to the public Tinyhat Hermes runtime."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any


class HatRepositoryRuntimeError(RuntimeError):
    """The local runtime could not complete a Hat repository action."""


def _contains_credential_field(value: Any) -> bool:
    forbidden = {"token", "password", "authorization", "private_key"}
    if isinstance(value, dict):
        return any(
            str(key).casefold() in forbidden or _contains_credential_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_credential_field(item) for item in value)
    return False


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
    # The runtime contract is value-blind. Fail closed if a future runtime
    # accidentally puts a credential-shaped field in plugin-visible output.
    if _contains_credential_field(result):
        raise HatRepositoryRuntimeError(
            "The runtime returned unsafe repository helper output."
        )
    return result


__all__ = ["HatRepositoryRuntimeError", "run_hat_repository"]
