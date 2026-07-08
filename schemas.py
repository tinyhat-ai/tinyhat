"""Tinyhat Hermes plugin tool schemas."""

TINYHAT_PLUGIN_VERSION_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

TINYHAT_TELL_JOKE_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

TINYHAT_SKILL_CATALOG_SCHEMA = {
    "type": "object",
    "description": (
        "Lists Tinyhat plugin skills with their plugin-qualified names and "
        "unqualified aliases. Use this when Hermes skill lookup/listing does "
        "not show Tinyhat plugin skills clearly."
    ),
    "properties": {},
    "required": [],
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
                "Required env-style secret name, for example EXA_API_KEY, "
                "OPENROUTER_API_KEY, GITHUB_TOKEN, or STRIPE_SECRET_KEY. "
                "Never use generic placeholders such as TINYHAT_SECRET, "
                "SECRET, API_KEY, or TOKEN."
            ),
        },
        "description": {
            "type": "string",
            "description": (
                "Required short human-readable description of what this "
                "secret is used for."
            ),
        },
    },
    "required": ["name", "description"],
    "additionalProperties": False,
}

TINYHAT_CODEX_AUTH_SCHEMA = {
    "type": "object",
    "description": (
        "Tinyhat Codex-auth helper for Telegram. Use prerequisite for a "
        "plain natural-language request to use a Codex subscription; it sends "
        "the ChatGPT Settings > Security screenshot and /codex_auth instruction "
        "without starting auth. "
        "Use start only after the user explicitly confirms the setting is on."
    ),
    "properties": {
        "action": {
            "type": "string",
            "enum": ["prerequisite", "start", "status", "log", "limits"],
            "description": (
                "Use prerequisite first for natural-language requests to "
                "connect ChatGPT/Codex. Use start only after the user "
                "confirms the ChatGPT Security setting is enabled. Use "
                "status, log, or limits for installed Codex auth inspection "
                "flows."
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
    "required": ["action"],
    "additionalProperties": False,
}

TINYHAT_PLUGIN_UPDATE_SCHEMA = {
    "type": "object",
    "description": (
        "Checks or applies the installed Tinyhat plugin update from the "
        "configured channel, usually channels/lts. Use status first when the "
        "agent may be running older plugin schemas."
    ),
    "properties": {
        "action": {
            "type": "string",
            "enum": ["status", "update"],
            "description": (
                "Use status to compare the installed plugin with the target "
                "channel. Use update only after the user/operator asks to "
                "apply the plugin update."
            ),
        },
        "confirmed": {
            "type": "boolean",
            "description": (
                "Set true with action=update only after the user/operator "
                "has asked to update the Tinyhat plugin on this Computer."
            ),
        },
        "restart_gateway": {
            "type": "boolean",
            "description": (
                "With action=update, set true when the Hermes Telegram "
                "gateway should be stopped and started after a plugin change "
                "so long-running commands/tools reload."
            ),
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}
