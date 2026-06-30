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
