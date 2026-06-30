---
name: tinyhat-platform
description: Explain how this Hermes agent should use Tinyhat platform capabilities. Use for Tinyhat-managed Computers, secrets, API keys, credentials, Codex auth, ChatGPT subscription auth, usage limits, settings, or questions about where the agent is running.
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
| Connect ChatGPT / OpenAI Codex auth or use the user's OpenAI paid access | Load `tinyhat:tinyhat-codex-auth`; reply once with the ChatGPT Security setting path, then put `/codex_auth` on its own line. Do not call the screenshot tool unless the user asks where the setting is. |
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

When the user asks to connect ChatGPT, OpenAI, Codex, a ChatGPT
subscription, ChatGPT Plus / Pro / Team, a paid ChatGPT account, their
own OpenAI access, or to stop using platform credits, treat it as a
Tinyhat Codex auth request by default. Do not ask a multiple-choice
clarification unless they explicitly ask for ChatGPT history/data or an
OpenAI API key.

Load `tinyhat:tinyhat-codex-auth` and follow its simple flow:

1. Reply once: ask the user to open `chatgpt.com` > Settings > Security,
   scroll to **Secure sign in with ChatGPT**, and turn on **Enable device
   code authorization for Codex**. Put `/codex_auth` on its own line as
   the action they should tap after they come back.
2. Do not call `tinyhat_codex_auth` in the default path. That screenshot
   tool is only for users who ask where the setting is or need the visual
   guide. The `/codex_auth` command sends an OpenAI auth button and then a
   separate copyable device code in Telegram.

Do not paste raw auth URLs unless the Tinyhat command reports that
Telegram delivery failed.

Do not ask for `auth.json`, passwords, refresh tokens, API keys, or
OAuth tokens. After the user signs in, use `/codex_auth_status` if you
need proof, and `/codex_limits` if they ask about remaining limits.

## Boundary

The runtime is the boring control plane: identity, heartbeat, install,
updates, and a closed maintenance command set. Product behavior belongs
in Tinyhat platform APIs plus this plugin's skills and tools. Do not
invent runtime commands for product features.
