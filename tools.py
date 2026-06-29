"""Small public Tinyhat plugin tools used by framework adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def plugin_version_payload() -> dict[str, str]:
    """Return the version of the Tinyhat plugin code currently loaded."""
    manifest_path = Path(__file__).resolve().parent / "hermes.plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = str(manifest.get("version") or "unknown").strip() or "unknown"
    return {
        "schema": "tinyhat_plugin_version_v1",
        "name": "tinyhat",
        "version": version,
    }


def plugin_version(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Hermes tool handler for reporting the loaded Tinyhat plugin version."""
    _ = args
    return json.dumps(plugin_version_payload(), sort_keys=True)


def joke_text(topic: str | None = None) -> str:
    """Return the deterministic joke used to prove the plugin is wired."""
    subject = topic.strip() if isinstance(topic, str) and topic.strip() else "runtime"
    return (
        f"Why did the Tinyhat {subject} carry a notebook? "
        "Because transparent skills should leave readable notes."
    )


def tell_joke(args: dict[str, Any] | None = None, **_: Any) -> str:
    """Hermes tool handler for the Tinyhat joke proof.

    Hermes can pass dispatcher metadata such as ``task_id`` to tool handlers.
    The Tinyhat plugin should ignore that metadata so the tool works from the
    first live agent interaction.
    """
    payload = args or {}
    return json.dumps(
        {
            "schema": "tinyhat_tell_joke_v1",
            "joke": joke_text(payload.get("topic")),
        },
        sort_keys=True,
    )
