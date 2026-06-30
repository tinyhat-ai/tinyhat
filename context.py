"""Tinyhat turn context for Hermes-managed Computers."""

from __future__ import annotations

import re
from typing import Any


TINYHAT_CONTEXT = """Tinyhat context: this Hermes agent runs on a Tinyhat-managed Computer.
- For API keys, tokens, passwords, webhook secrets, or credentials, use tinyhat_private_secret_handoff by default. Do not ask the user to paste secrets in chat and do not lead with manual .env editing unless the user explicitly asks for manual server operations.
- Choose meaningful env-style names such as EXA_API_KEY, OPENROUTER_API_KEY, GITHUB_TOKEN, or STRIPE_SECRET_KEY. Never use TINYHAT_SECRET for a known provider.
- When the user asks to connect ChatGPT, OpenAI, Codex, ChatGPT Plus/Pro/Team, a paid ChatGPT account, their Codex subscription, or to stop using Tinyhat/platform credits, load tinyhat:tinyhat-codex-auth and reply once with the ChatGPT Settings > Security path, then put /codex_auth on its own line as the next action. Do not call tinyhat_codex_auth for the default path because it creates duplicate messages; use that screenshot tool only when the user asks for help finding the setting. Do not ask a multiple-choice clarification unless they explicitly ask for ChatGPT history/data or an OpenAI API key.
- For OpenAI Codex auth or usage limits, prefer the Tinyhat-installed /codex_auth, /codex_auth_status, /codex_auth_log, and /codex_limits flows. The auth flow sends the Telegram button and copyable device code after the ChatGPT Security setting is confirmed; do not ask for auth.json, refresh tokens, passwords, or raw OAuth tokens.
- Load tinyhat:tinyhat-platform, tinyhat:tinyhat-private-secret, tinyhat:tinyhat-codex-auth, or tinyhat:tinyhat-plugin-version when you need the longer Tinyhat playbook."""

_CONTEXT_PHRASES = (
    "api key",
    "api token",
    "access token",
    "auth token",
    "bot token",
    "chatgpt account",
    "chatgpt plus",
    "chatgpt pro",
    "chatgpt subscription",
    "codex subscription",
    "github token",
    "llm plan",
    "openai account",
    "openai subscription",
    "oauth token",
    "paid chatgpt",
    "platform credits",
    "refresh token",
    "webhook secret",
    "usage limit",
    "usage limits",
    "sign in",
    "device code authorization",
    "start codex sign-in",
    "start codex sign in",
    "secure sign in",
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
    normalized_for_terms = re.sub(r"[_-]+", " ", normalized)
    if any(
        phrase in normalized or phrase in normalized_for_terms
        for phrase in _CONTEXT_PHRASES
    ):
        return True
    terms = set(re.findall(r"[a-z0-9]+", normalized_for_terms))
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
