"""Tinyhat turn context for Hermes-managed Computers."""

from __future__ import annotations

import re
from typing import Any


TINYHAT_CONTEXT = """Tinyhat context: this Hermes agent runs on a Tinyhat-managed Computer.
- For API keys, tokens, passwords, webhook secrets, or credentials, use tinyhat_private_secret_handoff by default. Do not ask the user to paste secrets in chat and do not lead with manual .env editing unless the user explicitly asks for manual server operations.
- Choose meaningful env-style names such as EXA_API_KEY, OPENROUTER_API_KEY, GITHUB_TOKEN, or STRIPE_SECRET_KEY. Never use TINYHAT_SECRET for a known provider.
- For OpenAI Codex auth or usage limits, prefer the Tinyhat-installed /codex_auth, /codex_auth_status, /codex_auth_log, and /codex_limits flows. The auth flow sends the Telegram button and copyable device code; do not ask for auth.json, refresh tokens, passwords, or raw OAuth tokens.
- Load tinyhat:tinyhat-platform, tinyhat:tinyhat-private-secret, or tinyhat:tinyhat-plugin-version when you need the longer Tinyhat playbook."""

_CONTEXT_PHRASES = (
    "api key",
    "api token",
    "access token",
    "auth token",
    "bot token",
    "github token",
    "oauth token",
    "refresh token",
    "webhook secret",
    "usage limit",
    "usage limits",
    "sign in",
)

_CONTEXT_TERMS = (
    "apikey",
    "secret",
    "secrets",
    "credential",
    "credentials",
    "password",
    "passwords",
    "exa",
    "openrouter",
    "stripe",
    "tavily",
    "firecrawl",
    "codex",
    "openai",
    "chatgpt",
    "quota",
    "credits",
    "subscription",
    "auth",
    "login",
    "settings",
    "tinyhat",
)


def should_inject_tinyhat_context(user_message: str, *, is_first_turn: bool = False) -> bool:
    """Return whether this turn benefits from Tinyhat operating context."""
    if is_first_turn:
        return True
    normalized = " ".join((user_message or "").lower().split())
    if any(phrase in normalized for phrase in _CONTEXT_PHRASES):
        return True
    terms = set(re.findall(r"[a-z0-9_]+", normalized))
    return any(term in terms for term in _CONTEXT_TERMS)


def inject_tinyhat_context(
    session_id: str | None = None,
    user_message: str = "",
    conversation_history: list[Any] | None = None,
    is_first_turn: bool = False,
    model: str | None = None,
    platform: str | None = None,
    **_: Any,
) -> dict[str, str] | None:
    """Hermes pre_llm_call hook that adds compact Tinyhat context when useful."""
    _ = (session_id, conversation_history, model, platform)
    if not should_inject_tinyhat_context(user_message, is_first_turn=is_first_turn):
        return None
    return {"context": TINYHAT_CONTEXT}
