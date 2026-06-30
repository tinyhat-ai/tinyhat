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

Do the work yourself. Do not tell the user to send `/codex_auth` as the
primary path. That command exists for manual fallback; this skill exists
so you can initiate the same process for the user.

First, send this screenshot to the user:

```text
skills/tinyhat-codex-auth/assets/chatgpt-enable-device-code-for-codex.png
```

Use a short caption:

```text
Before the sign-in works, please check ChatGPT Settings -> Security and
turn on "Enable device code authorization for Codex" if it is off.
```

If your current interface cannot attach an image, send that one-sentence
checklist in text and continue with the flow. Do not stop just because
the screenshot could not be attached.

Tinyhat installs this Telegram auth flow during Computer setup:

```text
/codex_auth
```

The command sends an OpenAI authorization button to Telegram, sends the
device code as a separate copyable message, waits for OpenAI to finish
the device flow on this Computer, switches Hermes to Codex auth, and
restarts the Telegram gateway so the next reply uses the new credential.

Start the installed flow yourself. Prefer invoking the installed quick
command directly if your interface supports that. Otherwise run the same
installed runtime helper:

```bash
PYTHONPATH="${TINYHAT_RUNTIME_PREFIX:-/opt/tinyhat-hermes-runtime}:${PYTHONPATH:-}" \
python3 -m hermes_runtime.telegram_codex_auth start
```

Only if both the quick command and runtime helper are unavailable should
you tell the user to send `/codex_auth` manually.

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
