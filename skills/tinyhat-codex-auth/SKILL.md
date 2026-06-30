---
name: tinyhat-codex-auth
description: Start Tinyhat's OpenAI Codex / ChatGPT subscription device-auth flow. Use when the user says things like "connect you to my ChatGPT account", "use my Codex subscription", "use my ChatGPT Plus/Pro/Team plan", "switch from platform credits", "use my own OpenAI paid access", or "connect OpenAI auth".
---

# Tinyhat Codex Auth

Use this when the user wants this Tinyhat-managed Hermes agent to use
their OpenAI Codex / ChatGPT subscription instead of Tinyhat-funded
platform credits.

Do not ask a multiple-choice clarification for common wording like
"connect my ChatGPT account" or "use my Codex subscription". Treat that
as a request to start Tinyhat's Codex auth flow. Only clarify if the user
explicitly asks for ChatGPT conversation history/data or for an OpenAI
API key instead of subscription auth.

## Start The Flow

Tinyhat installs this Telegram auth flow during Computer setup:

```text
/codex_auth
```

The command sends an OpenAI authorization button to Telegram, sends the
device code as a separate copyable message, waits for OpenAI to finish
the device flow on this Computer, switches Hermes to Codex auth, and
restarts the Telegram gateway so the next reply uses the new credential.

If you can invoke the installed quick command directly, start it
immediately. If this turn cannot invoke slash commands directly, run the
same installed runtime helper:

```bash
PYTHONPATH="${TINYHAT_RUNTIME_PREFIX:-/opt/tinyhat-hermes-runtime}:${PYTHONPATH:-}" \
python3 -m hermes_runtime.telegram_codex_auth start
```

Keep your user-facing reply short. Do not tell the user to edit config
files, run `hermes auth add ...`, paste `auth.json`, provide a refresh
token, or create an OpenAI API key.

## Message Contract

- The Tinyhat auth helper sends the button and device code itself.
- Do not paste the raw auth URL or duplicate the device code unless the
  helper explicitly reports that Telegram delivery failed.
- The device code is copyable but temporary. It is not the OAuth token.
- If the user says they signed in, use `/codex_auth_status` to verify.
- If they ask about remaining limits, use `/codex_limits`.
- If the flow fails or seems stuck, use `/codex_auth_log` and surface the
  bounded non-secret error. Do not guess.

## Helpful Copy

When the flow starts, a good short reply is:

```text
I started the OpenAI Codex sign-in flow. Tap the authorization button I
sent above, then paste the code from the next message. I will switch to
your Codex subscription when OpenAI finishes the sign-in.
```
