"""Tinyhat Hermes plugin adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import context, schemas, tools


def _joke_command_handler(raw_args: str = "") -> str:
    topic = raw_args.strip() or None
    return tools.joke_text(topic)


def _plugin_version_command_handler(raw_args: str = "") -> str:
    _ = raw_args
    payload = tools.plugin_version_payload()
    return f"Tinyhat plugin {payload['version']} is loaded in Hermes."


def _private_secret_command_handler(raw_args: str = "") -> str:
    parts = raw_args.strip().split(maxsplit=1)
    if not parts:
        return (
            "Tell me the specific secret name, for example "
            "/tinyhat_secret EXA_API_KEY Exa API key for search."
        )
    name = parts[0].strip()
    description = parts[1].strip() if len(parts) > 1 else f"{name} credential"
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
        name="tinyhat_get_platform_status",
        toolset="tinyhat",
        schema=schemas.TINYHAT_GET_PLATFORM_STATUS_SCHEMA,
        handler=tools.get_platform_status,
    )
    ctx.register_tool(
        name="tinyhat_credit",
        toolset="tinyhat",
        schema=schemas.TINYHAT_CREDIT_SCHEMA,
        handler=tools.credit,
    )
    ctx.register_tool(
        name="tinyhat_model_budget",
        toolset="tinyhat",
        schema=schemas.TINYHAT_MODEL_BUDGET_SCHEMA,
        handler=tools.model_budget,
    )
    ctx.register_tool(
        name="tinyhat_openrouter_credit_allocate",
        toolset="tinyhat",
        schema=schemas.TINYHAT_OPENROUTER_CREDIT_ALLOCATE_SCHEMA,
        handler=tools.openrouter_credit_allocate,
    )
    ctx.register_tool(
        name="tinyhat_contact_details",
        toolset="tinyhat",
        schema=schemas.TINYHAT_CONTACT_DETAILS_SCHEMA,
        handler=tools.contact_details,
    )
    ctx.register_tool(
        name="tinyhat_hats",
        toolset="tinyhat",
        schema=schemas.TINYHAT_HATS_SCHEMA,
        handler=tools.hats,
    )
    ctx.register_tool(
        name="tinyhat_tell_joke",
        toolset="tinyhat",
        schema=schemas.TINYHAT_TELL_JOKE_SCHEMA,
        handler=tools.tell_joke,
    )
    ctx.register_tool(
        name="tinyhat_skill_catalog",
        toolset="tinyhat",
        schema=schemas.TINYHAT_SKILL_CATALOG_SCHEMA,
        handler=tools.skill_catalog,
    )
    ctx.register_tool(
        name="tinyhat_private_secret_handoff",
        toolset="tinyhat",
        schema=schemas.TINYHAT_PRIVATE_SECRET_HANDOFF_SCHEMA,
        handler=tools.private_secret_handoff,
    )
    ctx.register_tool(
        name="tinyhat_slack_connect",
        toolset="tinyhat",
        schema=schemas.TINYHAT_SLACK_CONNECT_SCHEMA,
        handler=tools.slack_connect,
    )
    ctx.register_tool(
        name="tinyhat_slack_disconnect",
        toolset="tinyhat",
        schema=schemas.TINYHAT_SLACK_DISCONNECT_SCHEMA,
        handler=tools.slack_disconnect,
    )
    ctx.register_tool(
        name="tinyhat_credentials",
        toolset="tinyhat",
        schema=schemas.TINYHAT_CREDENTIALS_SCHEMA,
        handler=tools.credentials,
    )
    ctx.register_tool(
        name="tinyhat_google_workspace",
        toolset="tinyhat",
        schema=schemas.TINYHAT_GOOGLE_WORKSPACE_SCHEMA,
        handler=tools.google_workspace,
    )
    ctx.register_tool(
        name="tinyhat_google_workspace_app",
        toolset="tinyhat",
        schema=schemas.TINYHAT_GOOGLE_WORKSPACE_APP_SCHEMA,
        handler=tools.google_workspace_app,
    )
    ctx.register_tool(
        name="tinyhat_google_workspace_app_manager",
        toolset="tinyhat",
        schema=schemas.TINYHAT_GOOGLE_WORKSPACE_APP_MANAGER_SCHEMA,
        handler=tools.google_workspace_app_manager,
    )
    ctx.register_tool(
        name="tinyhat_codex_auth",
        toolset="tinyhat",
        schema=schemas.TINYHAT_CODEX_AUTH_SCHEMA,
        handler=tools.codex_auth,
    )
    ctx.register_tool(
        name="tinyhat_plugin_update",
        toolset="tinyhat",
        schema=schemas.TINYHAT_PLUGIN_UPDATE_SCHEMA,
        handler=tools.plugin_update,
    )
    ctx.register_hook("pre_llm_call", context.inject_tinyhat_context)
    # Hermes registers plugin slash commands by their canonical names, then
    # Telegram shows them with underscores and maps inbound underscores back to
    # hyphens before dispatch.
    ctx.register_command(
        "tinyhat-joke",
        _joke_command_handler,
        description="Tell a short Tinyhat plugin wiring-test joke.",
    )
    ctx.register_command(
        "tinyhat-plugin-version",
        _plugin_version_command_handler,
        description="Show the Tinyhat plugin version currently loaded in Hermes.",
    )
    ctx.register_command(
        "tinyhat-secret",
        _private_secret_command_handler,
        description="Start a secure Tinyhat Mini App handoff for a secret.",
    )
    _register_skills(ctx)
