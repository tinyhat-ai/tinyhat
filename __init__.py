"""Tinyhat Hermes plugin adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import schemas, tools


def _joke_command_handler(raw_args: str = "") -> str:
    topic = raw_args.strip() or None
    return tools.joke_text(topic)


def _plugin_version_command_handler(raw_args: str = "") -> str:
    _ = raw_args
    payload = tools.plugin_version_payload()
    return f"Tinyhat plugin {payload['version']} is loaded in Hermes."


def _private_secret_command_handler(raw_args: str = "") -> str:
    parts = raw_args.strip().split(maxsplit=1)
    name = parts[0].strip() if parts else "TINYHAT_SECRET"
    description = parts[1].strip() if len(parts) > 1 else None
    return tools.private_secret_handoff(
        {"name": name, "description": description},
    )


def _register_skills(ctx: Any) -> list[str]:
    skills_dir = Path(__file__).parent / "skills"
    registered: list[str] = []
    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.exists():
            ctx.register_skill(child.name, skill_md)
            registered.append(child.name)
    return registered


def register(ctx: Any) -> None:
    """Register Tinyhat skills and the first Hermes smoke-test tool."""
    ctx.register_tool(
        name="tinyhat_plugin_version",
        toolset="tinyhat",
        schema=schemas.TINYHAT_PLUGIN_VERSION_SCHEMA,
        handler=tools.plugin_version,
    )
    ctx.register_tool(
        name="tinyhat_tell_joke",
        toolset="tinyhat",
        schema=schemas.TINYHAT_TELL_JOKE_SCHEMA,
        handler=tools.tell_joke,
    )
    ctx.register_tool(
        name="tinyhat_private_secret_handoff",
        toolset="tinyhat",
        schema=schemas.TINYHAT_PRIVATE_SECRET_HANDOFF_SCHEMA,
        handler=tools.private_secret_handoff,
    )
    ctx.register_command(
        name="tinyhat_joke",
        handler=_joke_command_handler,
        description="Tell a short Tinyhat plugin wiring-test joke.",
        args_hint="[topic]",
    )
    ctx.register_command(
        name="tinyhat_plugin_version",
        handler=_plugin_version_command_handler,
        description="Show the Tinyhat plugin version currently loaded in Hermes.",
        args_hint="",
    )
    ctx.register_command(
        name="tinyhat_secret",
        handler=_private_secret_command_handler,
        description="Start a secure Tinyhat Mini App handoff for a secret.",
        args_hint="SECRET_NAME [description]",
    )
    _register_skills(ctx)
