# Capabilities

The current capability list is intentionally small.

| Capability | Status | Why it exists |
| --- | --- | --- |
| `tinyhat_plugin_version` | Available now | Proves which Tinyhat plugin version Hermes has loaded for the live agent. |
| `tinyhat_tell_joke` | Available now | Proves Hermes loaded the Tinyhat plugin and can call a plugin tool. |
| `tinyhat_skill_catalog` | Available now | Lists Tinyhat plugin skills with `tinyhat:<skill>` qualified names and unqualified aliases. |
| `tinyhat_private_secret_handoff` | Available now | Lets a user enter a secret in a Telegram Mini App while Tinyhat stores only short-lived ciphertext. |
| `tinyhat-codex-auth` skill | Available now | Teaches the agent to start and inspect the Tinyhat-installed OpenAI Codex / ChatGPT subscription auth flow. |
| `tinyhat_plugin_update` | Available now | Checks and applies the configured plugin channel through installed runtime commands. |
| `pre_llm_call` context | Available now | Gives Hermes a short Tinyhat operating reminder on first turn and Tinyhat-sensitive requests. |

Each capability should be visible in this document, represented by a small
tool or skill, and covered by validation.

## Private Secret Handoff

This capability is used when the user wants to save an API key, token,
password, or credential for their agent.

The agent must not ask for the secret in chat. Instead, it calls
`tinyhat_private_secret_handoff`. The Computer creates a temporary key
pair, the Mini App encrypts the entered value with the public key, and the
Computer decrypts the submitted ciphertext with the temporary private key.
Tinyhat stores only ciphertext during the short handoff window.
After save, the Computer uses a survivor worker for the gateway refresh when
systemd is available and claims either confirmed gateway readiness or a visible
gateway restart failure.

## Tinyhat Platform Context

The plugin injects a short context note when the user asks about secrets,
credentials, Tinyhat, Codex auth, usage limits, plugin updates, skill
lookup, QA reports, or on the first turn of a session. The context tells
the agent to prefer Tinyhat private secret entry for credentials,
Tinyhat's installed Codex commands for OpenAI Codex auth, the plugin
catalog for missing skill lookup, and runtime channel commands for stale
installed plugins. The longer playbook lives in
`skills/tinyhat-platform/SKILL.md`.

## Codex / ChatGPT Subscription Auth

This capability is used when the user says something like "connect you to
my ChatGPT account", "use my Codex subscription", "use my own OpenAI paid
access", or "switch from platform credits".

The agent should load `tinyhat:tinyhat-codex-auth` and call
`tinyhat_codex_auth` once with `{"action": "prerequisite"}`. The helper
sends the ChatGPT Settings > Security screenshot and puts `/codex_auth`
on its own line. The user opens `chatgpt.com` > Settings > Security,
scrolls to **Secure sign in with ChatGPT**, turns on **Enable device code
authorization for Codex**, and then taps `/codex_auth` in the same
Telegram chat. That command starts the Tinyhat-installed auth flow. The
auth flow sends an OpenAI
authorization button and a separate copyable device code to Telegram,
waits for OpenAI to complete device auth on the Computer, switches
Hermes to Codex auth, and restarts the Telegram gateway. The agent should
not send duplicate text replies, call the prerequisite action twice, or
ask for `auth.json`, refresh tokens, passwords, or OpenAI API keys for
this subscription-auth path. For follow-up inspection, the same tool
accepts `{"action": "status"}`, `{"action": "log"}`, or
`{"action": "limits"}` and returns bounded runtime output.

## Plugin Update And Skill Discovery

These capabilities are used when the live Computer is behind its configured
plugin channel or when Hermes cannot find Tinyhat plugin skills by their
unqualified names.

For skill lookup failures, the agent calls `tinyhat_skill_catalog` and
uses the returned `qualified_name` values, for example
`tinyhat:tinyhat-codex-auth`. This keeps Tinyhat plugin skills
discoverable even when a generic `skills_list` output omits
plugin-qualified entries.

For stale installed plugin reports, the agent calls
`tinyhat_plugin_update` with `{"action": "status"}` first. When the
runtime reports `update_available=true` or `decision=target_ref_changed`,
the agent applies the update only after the user/operator asks for it:
`{"action": "update", "confirmed": true, "restart_gateway": true}`. The
tool delegates to the installed runtime commands rather than composing
arbitrary shell commands in chat.

## Capability Rules

- Capabilities must have clear names.
- Skills should explain when to use a capability and what not to expose.
- Privileged work should go through Tinyhat platform APIs using the
  Computer identity provided by the runtime.
- Secrets, signed URLs, and private platform endpoints must not be
  printed into chat.
- Secret values must be entered in dedicated user-facing flows, not chat
  messages or skill instructions.
