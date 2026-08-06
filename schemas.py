"""Tinyhat Hermes plugin tool schemas."""

TINYHAT_PLUGIN_VERSION_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

TINYHAT_GET_PLATFORM_STATUS_SCHEMA = {
    "type": "object",
    "description": (
        "Reads safe, non-secret Tinyhat platform context for this authenticated "
        "Computer, including its state, assignment, configuration revisions, and "
        "installed package inventory. It never returns tokens or credentials."
    ),
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

TINYHAT_HATS_SCHEMA = {
    "type": "object",
    "description": (
        "Creates, lists, inspects, updates, and permanently deletes owner-scoped "
        "Tinyhat Hats; commits guarded non-secret files to their private repos; "
        "and defines, configures, lists, or removes Computer-local Hat credentials "
        "without returning values."
    ),
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "create",
                "list",
                "get",
                "update",
                "delete",
                "put_file",
                "define_credential",
                "configure_credentials",
                "list_credentials",
                "remove_credential",
            ],
        },
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 127,
            "description": "Required human-readable hat name for create.",
        },
        "customer_email": {
            "type": "string",
            "minLength": 3,
            "maxLength": 320,
            "description": "Required work email for the one customer this hat serves.",
        },
        "key": {
            "type": "string",
            "minLength": 1,
            "maxLength": 47,
            "pattern": "^[a-z0-9][a-z0-9_-]*$",
            "description": (
                "Optional stable lowercase key. Omit it to derive one from the name."
            ),
        },
        "default_bot_username": {
            "type": "string",
            "minLength": 5,
            "maxLength": 32,
            "pattern": "^@?[A-Za-z][A-Za-z0-9_]{1,28}bot$",
            "description": (
                "Optional Telegram bot username to prefill for the customer. It "
                "must start with a letter and end in bot."
            ),
        },
        "default_bot_display_name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "description": (
                "Optional Telegram bot display name to prefill for the customer."
            ),
        },
        "identifier": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255,
            "description": (
                "Required key or canonical handle for get, update, delete, "
                "put_file, define_credential, configure_credentials, "
                "list_credentials, and remove_credential."
            ),
        },
        "public_title": {
            "type": "string",
            "minLength": 1,
            "maxLength": 127,
            "description": "Required new marketplace title for action=update.",
        },
        "path": {
            "type": "string",
            "minLength": 1,
            "maxLength": 240,
            "description": (
                "Required relative repo path for put_file, for example "
                "skills/forecasting/SKILL.md. Secret and credential paths are blocked."
            ),
        },
        "content": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100000,
            "description": (
                "Required UTF-8 text for put_file. Never include API keys, tokens, "
                "passwords, private keys, or other secret values."
            ),
        },
        "credential_name": {
            "type": "string",
            "pattern": "^[A-Z_][A-Z0-9_]{0,126}$",
            "description": (
                "Exact env-style Hat credential name for define_credential or remove_credential."
            ),
        },
        "description": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500,
            "description": ("Required safe purpose for define_credential. Never include a value."),
        },
        "confirmed": {
            "type": "boolean",
            "description": (
                "True only after the user explicitly asks to remove this exact "
                "credential from this exact Hat, or to permanently delete this "
                "exact Hat and its private repository."
            ),
        },
    },
    "required": ["action"],
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
        "hat_identifier": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255,
            "description": (
                "Optional Hat key or canonical handle. When set, the browser-encrypted "
                "plaintext is written only to that Hat's Computer-local secret store, "
                "not Hermes global configuration."
            ),
        },
    },
    "required": ["name", "description"],
    "additionalProperties": False,
}

TINYHAT_SLACK_CONNECT_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
    "description": (
        "Start Tinyhat's Hermes-native Slack setup. Sends the current Hermes "
        "Agent-view manifest, Slack app creation guide, and browser-encrypted "
        "credential bundle to Telegram."
    ),
}

TINYHAT_SLACK_DISCONNECT_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
    "description": (
        "Start Tinyhat's owner-confirmed Slack disconnect. The Computer asks "
        "Slack to revoke the bot token when possible, removes the complete "
        "local Slack bundle, and restarts Hermes before reporting success."
    ),
}


TINYHAT_CREDENTIALS_SCHEMA = {
    "type": "object",
    "description": (
        "Lists value-blind credential metadata on this Computer or sends an "
        "expiring Telegram confirmation that triggers Computer-side deletion. "
        "This tool never returns credential values."
    ),
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "remove"],
            "description": (
                "Use list to retrieve names/descriptions and related matches. Use "
                "remove only after selecting the intended credential; the platform "
                "sends the final Telegram confirmation."
            ),
        },
        "query": {
            "type": "string",
            "maxLength": 200,
            "description": "Optional case-insensitive name or description search for list.",
        },
        "handoff_id": {
            "type": "string",
            "maxLength": 64,
            "description": "Preferred opaque selector returned by action=list.",
        },
        "name": {
            "type": "string",
            "maxLength": 127,
            "description": (
                "Exact env-style name fallback for remove when handoff_id is not "
                "available. Ambiguous or missing matches return related credentials."
            ),
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}

TINYHAT_GOOGLE_WORKSPACE_SCHEMA = {
    "type": "object",
    "description": (
        "Connect, inspect, choose or change permissions for, or disconnect Google "
        "Workspace accounts on this Tinyhat Computer. A bare connect requests identity only. "
        "Workspace data access must be selected explicitly with one or more implemented "
        "presets or an exact custom subset of the public scope manifest. Pending Google "
        "verification may produce a provider warning but does not block an implemented "
        "scope. Unknown, unimplemented, and legacy-only requests stop before an "
        "authorization URL or worker is created and return review_required. Never "
        "substitute the nearest broader preset for an exact or Custom request. Legacy "
        "named profiles remain available for compatibility. The user provides no "
        "Google Cloud project or OAuth secret."
    ),
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "connect",
                "choose_permissions",
                "status",
                "set_permissions",
                "disconnect",
            ],
            "description": (
                "Use choose_permissions when the user wants Google or Gmail access "
                "but has not said what the Computer should be allowed to do; it sends "
                "a concise Telegram Mini App chooser. Use connect to add an account "
                "with a known exact preset or scope set or, with account_id, retain the "
                "additive behavior by combining current and requested scopes. Use "
                "set_permissions with account_id to replace one account's permissions "
                "with the exact named profile or scope set. "
                "Connect and permission changes send one native Telegram button "
                "without returning a plain authorization URL, status to show safe "
                "account metadata, or disconnect to send the platform-owned "
                "two-stage Telegram revoke prompt. Disconnect never trusts a "
                "model-supplied confirmation boolean."
            ),
        },
        "profile": {
            "type": "string",
            "enum": [
                "workspace_recommended",
                "workspace_readonly",
                "gmail_send",
                "calendar_write",
                "gmail_send_calendar_write",
            ],
            "description": (
                "Deprecated legacy permission profile for action=connect or "
                "action=set_permissions. New requests should use presets or scopes. "
                "Do not combine profile with presets or scopes. Omission means "
                "identity-only for connect; set_permissions requires an explicit "
                "selection."
            ),
        },
        "presets": {
            "type": "array",
            "minItems": 1,
            "maxItems": 7,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "enum": [
                    "mail_reader",
                    "mail_sender",
                    "workspace_reader",
                    "mail_writer",
                    "inbox_manager",
                    "calendar_coordinator",
                    "file_collaborator",
                ],
            },
            "description": (
                "One or more composable implemented presets: Mail Reader reads Gmail "
                "without changing it; Mail Sender only sends confirmed email and "
                "cannot read the inbox or manage drafts; Workspace Reader reads "
                "Gmail messages, threads, and settings, Calendar events, and Drive; "
                "Mail Writer creates and manages drafts and can send because Google's "
                "gmail.compose scope includes sending; "
                "Inbox Manager reads and manages Gmail messages, drafts, and "
                "labels; Calendar Coordinator manages events; File Collaborator "
                "works with files Tinyhat creates or files you explicitly share with "
                "the app, not other Drive files. Tinyhat "
                "normalizes overlapping scopes to the narrowest equivalent request. "
                "Use a preset only when it exactly covers the requested work; never "
                "choose the nearest broader preset."
            ),
        },
        "scopes": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "items": {"type": "string", "minLength": 1, "maxLength": 512},
            "description": (
                "Exact custom Google OAuth scopes requested with action=connect or "
                "action=set_permissions. Tinyhat adds openid, email, and profile, "
                "normalizes superseded scopes, and allows only scopes declared in the "
                "versioned public manifest. Requestable subsets and unions may launch "
                "even while Google verification is pending; an unimplemented scope "
                "returns review_required before OAuth. An explicit Custom request "
                "must remain exact and must never be coerced to a nearby preset. "
                "Requires reason; it may extend presets but cannot be combined with "
                "the deprecated profile input."
            ),
        },
        "reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": 280,
            "description": (
                "Short user-facing explanation of why custom scopes are needed. "
                "Required with scopes and not accepted with a named profile."
            ),
        },
        "account_id": {
            "type": "string",
            "pattern": "^gwo_[A-Za-z0-9_-]{1,60}$",
            "description": (
                "Opaque account selector returned by status. Required for "
                "set_permissions and whenever more than one account is connected. "
                "Never use or expose the Google subject as an account selector."
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
        "supplies service-specific operation guidance across Google Workspace; "
        "Tinyhat bridges only API roots audited for the pinned gws release while "
        "blocking auth, setup, export, persistent-server, unsafe file-I/O, and "
        "unbounded operations."
    ),
    "properties": {
        "argv": {
            "type": "array",
            "minItems": 1,
            "maxItems": 64,
            "items": {"type": "string", "minLength": 1, "maxLength": 4096},
            "description": (
                "Opaque gws arguments supplied by Hermes's native Google Workspace "
                "skill. Use a dotted method only after schema, for example "
                "['schema', 'gmail.users.messages.list']; for an API call split the "
                "method into argv items, for example ['gmail', 'users', 'messages', "
                "'list', '--params', '{...}']. Put path/query JSON in --params and "
                "request-body JSON in --json. Never put a dotted method in argv[0] or "
                "use wrapper shorthand such as 'gmail search'. Do not include the gws "
                "executable, auth/setup/login/export/mcp "
                "commands, unaudited/local/synthetic API roots, unsafe file-I/O flags, "
                "or unbounded pagination such as --page-all."
            ),
        },
        "effect": {
            "type": "string",
            "enum": ["read", "write"],
            "description": (
                "Declare whether this invocation only reads Google data or may "
                "change external state. Write commands require a separate exact-argv "
                "confirmation independently of Google OAuth consent."
            ),
        },
        "confirmed": {
            "type": "boolean",
            "description": (
                "Set true for effect=write only after the user explicitly confirms "
                "the exact external operation. Google OAuth consent does not count."
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
        "account_id": {
            "type": "string",
            "pattern": "^gwo_[A-Za-z0-9_-]{1,60}$",
            "description": (
                "Opaque account selector returned by tinyhat_google_workspace status. "
                "May be omitted only when exactly one account is connected."
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
