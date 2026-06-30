# Capabilities

The current capability list is intentionally small.

| Capability | Status | Why it exists |
| --- | --- | --- |
| `tinyhat_plugin_version` | Available now | Proves which Tinyhat plugin version Hermes has loaded for the live agent. |
| `tinyhat_tell_joke` | Available now | Proves Hermes loaded the Tinyhat plugin and can call a plugin tool. |
| `tinyhat_private_secret_handoff` | Available now | Lets a user enter a secret in a Telegram Mini App while Tinyhat stores only short-lived ciphertext. |
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

## Tinyhat Platform Context

The plugin injects a short context note when the user asks about secrets,
credentials, Tinyhat, Codex auth, usage limits, or on the first turn of a
session. The context tells the agent to prefer Tinyhat private secret
entry for credentials and Tinyhat's installed Codex commands for OpenAI
Codex auth. The longer playbook lives in `skills/tinyhat-platform/SKILL.md`.

## Capability Rules

- Capabilities must have clear names.
- Skills should explain when to use a capability and what not to expose.
- Privileged work should go through Tinyhat platform APIs using the
  Computer identity provided by the runtime.
- Secrets, signed URLs, and private platform endpoints must not be
  printed into chat.
- Secret values must be entered in dedicated user-facing flows, not chat
  messages or skill instructions.
