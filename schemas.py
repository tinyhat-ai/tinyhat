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
            "description": "Env-style secret name, for example OPENROUTER_API_KEY.",
        },
        "description": {
            "type": "string",
            "description": "Short human reminder for what this secret is used for.",
        },
        "expires_in_seconds": {
            "type": "integer",
            "description": "Optional handoff timeout. Defaults to 300 seconds.",
            "minimum": 60,
            "maximum": 600,
        },
    },
    "required": ["name"],
    "additionalProperties": False,
}
