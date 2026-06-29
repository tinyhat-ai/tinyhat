"""Tinyhat Hermes plugin adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import schemas, tools


def _command_handler(raw_args: str = "") -> str:
    topic = raw_args.strip() or None
    return tools.joke_text(topic)


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
        name="tinyhat_tell_joke",
        toolset="tinyhat",
        schema=schemas.TINYHAT_TELL_JOKE_SCHEMA,
        handler=tools.tell_joke,
    )
    ctx.register_command(
        name="tinyhat_joke",
        handler=_command_handler,
        description="Tell a short Tinyhat plugin wiring-test joke.",
        args_hint="[topic]",
    )
    _register_skills(ctx)
