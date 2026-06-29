"""Small public Tinyhat plugin tools used by framework adapters."""

from __future__ import annotations

import json
from typing import Any


def joke_text(topic: str | None = None) -> str:
    """Return the deterministic joke used to prove the plugin is wired."""
    subject = topic.strip() if isinstance(topic, str) and topic.strip() else "runtime"
    return (
        f"Why did the Tinyhat {subject} carry a notebook? "
        "Because transparent skills should leave readable notes."
    )


def tell_joke(args: dict[str, Any] | None = None) -> str:
    """Hermes tool handler for the Tinyhat joke proof."""
    payload = args or {}
    return json.dumps(
        {
            "schema": "tinyhat_tell_joke_v1",
            "joke": joke_text(payload.get("topic")),
        },
        sort_keys=True,
    )
