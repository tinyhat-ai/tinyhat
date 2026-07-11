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
                "Required short human-readable description of what this secret is used for."
            ),
        },
    },
    "required": ["name", "description"],
    "additionalProperties": False,
}

TINYHAT_GOOGLE_WORKSPACE_SCHEMA = {
    "type": "object",
    "description": (
        "Connect, inspect, or disconnect this Tinyhat Computer's Google Workspace "
        "account using one plugin-owned, platform-allowlisted permission profile. "
        "The default profile includes identity plus read-only Gmail, Calendar, and "
        "Drive. Named upgrades can add Gmail sending, Calendar event writing, or "
        "both while retaining existing granted write permissions. The user provides "
        "no Google Cloud project or OAuth secret."
    ),
    "properties": {
        "action": {
            "type": "string",
            "enum": ["connect", "status", "disconnect"],
            "description": (
                "Use connect to send one native Connect Google Telegram button "
                "without returning a plain authorization URL, status to show safe "
                "account metadata, or disconnect to send the platform-owned "
                "two-stage Telegram revoke prompt. Disconnect never trusts a "
                "model-supplied confirmation boolean."
            ),
        },
        "confirmed": {
            "type": "boolean",
            "description": (
                "Accepted only with action=connect and a write profile, after the "
                "user explicitly confirms that permission upgrade. Disconnect "
                "confirmation happens only through the tool-sent Telegram buttons. "
                "This does not confirm a later email send or Calendar event change."
            ),
        },
        "profile": {
            "type": "string",
            "enum": [
                "workspace_readonly",
                "gmail_send",
                "calendar_write",
                "gmail_send_calendar_write",
            ],
            "description": (
                "High-level allowlisted permission profile accepted only with "
                "action=connect. Omit for workspace_readonly. Use gmail_send, "
                "calendar_write, or gmail_send_calendar_write only after explicit "
                "permission-upgrade confirmation. Existing granted write permissions "
                "are preserved automatically; arbitrary scopes are never accepted."
            ),
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}

TINYHAT_GOOGLE_WORKSPACE_APP_SCHEMA = {
    "type": "object",
    "description": (
        "Run bounded argv through Tinyhat's pinned gws app using this Computer's "
        "assignment-verified Google access. Hermes's native Google Workspace skill "
        "supplies service-specific operation guidance; Tinyhat only bridges access."
    ),
    "properties": {
        "argv": {
            "type": "array",
            "minItems": 1,
            "maxItems": 64,
            "items": {"type": "string", "minLength": 1, "maxLength": 4096},
            "description": (
                "Opaque gws arguments supplied by Hermes's native Google Workspace "
                "skill. Do not include the gws executable, auth/setup/login/export "
                "commands, or unbounded pagination such as --page-all."
            ),
        },
        "effect": {
            "type": "string",
            "enum": ["read", "write"],
            "description": (
                "Declare whether this invocation only reads Google data or may "
                "change external state. Write commands require a separate exact-argv "
                "confirmation after any permission upgrade."
            ),
        },
        "confirmed": {
            "type": "boolean",
            "description": (
                "Set true for effect=write only after the user explicitly confirms "
                "the exact external operation. Permission-upgrade confirmation does "
                "not count."
            ),
        },
        "confirmation_id": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
            "description": (
                "For a confirmed write, repeat the exact confirmation_id returned by "
                "the tool's confirmation_required response for the unchanged argv."
            ),
        },
    },
    "required": ["argv", "effect"],
    "additionalProperties": False,
}

TINYHAT_GOOGLE_WORKSPACE_APP_MANAGER_SCHEMA = {
    "type": "object",
    "description": (
        "Inspect, install, or uninstall Tinyhat's pinned and integrity-verified "
        "Google Workspace CLI app. Hermes's native Google Workspace skill supplies "
        "operation guidance. Installation never starts another OAuth flow and "
        "requires explicit user approval."
    ),
    "properties": {
        "action": {
            "type": "string",
            "enum": ["status", "install", "uninstall"],
            "description": (
                "Use status to inspect safe managed metadata. Use install or "
                "uninstall only after explicit user approval."
            ),
        },
        "confirmed": {
            "type": "boolean",
            "description": (
                "Set true for install or uninstall only after the user explicitly "
                "approves that managed app change."
            ),
        },
    },
    "required": ["action"],
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
