"""Shared Tinyhat tool error payload helpers."""

from __future__ import annotations

import json
from typing import Any


def tool_error_json(
    *,
    tool: str,
    error_name: str,
    message: str,
    missing: list[str] | None = None,
    expected: dict[str, Any] | None = None,
    example_call: dict[str, Any] | None = None,
) -> str:
    """Return a stable JSON error that helps the agent self-correct."""
    payload: dict[str, Any] = {
        "schema": "tinyhat_tool_error_v1",
        "tool": tool,
        "status": "error",
        "error": error_name,
        "message": message,
    }
    if missing:
        payload["missing"] = missing
    if expected:
        payload["expected"] = expected
    if example_call:
        payload["example_call"] = example_call
    return json.dumps(payload, sort_keys=True)
