---
name: tinyhat-platform
description: Explain how this Hermes agent should use Tinyhat platform capabilities. Use for Tinyhat-managed Computers, secrets, API keys, credentials, Codex auth, usage limits, settings, or questions about where the agent is running.
---

# Tinyhat Platform

You are running on a Tinyhat-managed Hermes Computer. Tinyhat provides
the safe platform flows around Hermes; Hermes is still the agent
framework.

Use this as the default routing map:

| User intent | Default Tinyhat route |
| --- | --- |
| Add or save an API key, token, password, webhook secret, or credential | Call `tinyhat_private_secret_handoff` once. |
| Ask which Tinyhat plugin is running | Call `tinyhat_plugin_version`. |
| Check that the Tinyhat plugin exists | Call `tinyhat_tell_joke` or `tinyhat_plugin_version`. |
| Connect OpenAI Codex auth or use the user's OpenAI paid access | Use the installed `/codex_auth` flow. |
| Check Codex auth | Use `/codex_auth_status`. |
| Inspect recent Codex auth output | Use `/codex_auth_log`. |
| Show Codex usage limits | Use `/codex_limits`. |

## Secrets

For secrets and credentials, Tinyhat private secret entry is the default.
Do not lead with manual `.env` editing. Do not ask the user to paste a
secret into chat.

When the user says something like "add my Exa API key":

1. Choose the specific env-style name, for example `EXA_API_KEY`.
2. Call `tinyhat_private_secret_handoff` with `name` and a short
   description.
3. Let the Tinyhat-sent button stand.
4. Keep the chat reply short.

Load `tinyhat:tinyhat-private-secret` when you need the full naming and
failure-handling rules.

## Codex Auth

Tinyhat installs Telegram commands for Codex auth during Computer setup.
The important one is `/codex_auth`.

When the user asks to connect OpenAI Codex or their OpenAI paid access:

1. Prefer the Tinyhat `/codex_auth` flow. If your interface can run
   slash commands, run `/codex_auth`. If it cannot, tell the user to
   send `/codex_auth`.
2. The command sends an OpenAI auth button and then a separate copyable
   device code in Telegram.
3. Do not paste raw auth URLs unless the Tinyhat command reports that
   Telegram delivery failed.
4. Do not ask for `auth.json`, passwords, refresh tokens, API keys, or
   OAuth tokens.
5. After the user signs in, use `/codex_auth_status` if you need proof,
   and `/codex_limits` if they ask about remaining limits.

## Boundary

The runtime is the boring control plane: identity, heartbeat, install,
updates, and a closed maintenance command set. Product behavior belongs
in Tinyhat platform APIs plus this plugin's skills and tools. Do not
invent runtime commands for product features.
