"""Tinyhat Hermes plugin tool schemas."""

TINYHAT_PLUGIN_VERSION_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

TINYHAT_TELL_JOKE_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {
            "type": "string",
            "description": "Optional topic to gently include in the joke.",
        }
    },
    "additionalProperties": False,
}

TINYHAT_PRIVATE_SECRET_HANDOFF_SCHEMA = {
    "type": "object",
    "description": (
        "Default Tinyhat way to add API keys, tokens, passwords, webhook secrets, "
        "or other credentials to this Hermes Computer. Use this instead of telling "
        "the user to edit .env files or paste secret values in chat."
    ),
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "Specific env-style secret name chosen from the user request, "
                "for example EXA_API_KEY for an Exa API key. Never use "
                "generic placeholders such as TINYHAT_SECRET, SECRET, API_KEY, or TOKEN."
            ),
        },
        "description": {
            "type": "string",
            "description": "Short human reminder for what this secret is used for.",
        },
    },
    "required": ["name"],
    "additionalProperties": False,
}

TINYHAT_CODEX_AUTH_SCHEMA = {
    "type": "object",
    "description": (
        "Starts Tinyhat's OpenAI Codex device-code auth flow for Telegram. "
        "First sends the prerequisite screenshot/reminder with /codex_auth as "
        "the next action. The user normally taps that Telegram command to start "
        "the installed runtime helper that delivers the OpenAI auth button and "
        "code."
    ),
    "properties": {
        "action": {
            "type": "string",
            "enum": ["prerequisite", "start"],
            "description": (
                "Use prerequisite first. Use start only after the user confirms "
                "they enabled device-code authorization for Codex."
            ),
        },
        "confirmed": {
            "type": "boolean",
            "description": (
                "Set true with action=start only after the user confirms the "
                "ChatGPT Security toggle is on."
            ),
        },
    },
    "additionalProperties": False,
}
