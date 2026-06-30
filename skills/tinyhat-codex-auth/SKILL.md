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

## Step 1: Confirm The ChatGPT Setting

Do the work yourself. Do not tell the user to send `/codex_auth` as the
primary path. That command exists for manual fallback; this skill exists
so you can initiate the same process for the user.

First call `tinyhat_codex_auth` with:

```json
{"action": "prerequisite"}
```

The tool sends the ChatGPT device-code setting screenshot to Telegram.
After that, ask the user to confirm the setting is enabled. Stop there.
Do not start the auth helper in the same turn.

The tool uses this bundled screenshot:

```text
skills/tinyhat-codex-auth/assets/chatgpt-enable-device-code-for-codex.png
```

with this short caption:

```text
Open chatgpt.com > Settings > Security, scroll to "Secure sign in with
ChatGPT", then turn on "Enable device code authorization for Codex".
Reply here when it is on.
```

If the tool is unavailable, send that one-sentence checklist in text and
ask the user to confirm. Do not search for the image path in chat, and do
not start auth before the user confirms.

The user must do this on their side:

1. Open `chatgpt.com`.
2. Go to Settings.
3. Open Security.
4. Scroll to **Secure sign in with ChatGPT**.
5. Turn on **Enable device code authorization for Codex**.

Personal accounts can usually turn this on directly. Team, Business, and
Enterprise accounts may require a workspace admin if the toggle is
disabled.

## Step 2: Start Auth After Confirmation

When the user confirms the setting is on, call `tinyhat_codex_auth` with:

```json
{"action": "start", "confirmed": true}
```

Only this second call starts the installed auth helper that sends the
OpenAI authorization button and copyable code.

Let the tool's Telegram messages stand. Do not send a second link or a
second code in your own reply.

Tinyhat installs this Telegram auth flow during Computer setup:

```text
/codex_auth
```

The command sends an OpenAI authorization button to Telegram, sends the
device code as a separate copyable message, waits for OpenAI to finish
the device flow on this Computer, switches Hermes to Codex auth, and
restarts the Telegram gateway so the next reply uses the new credential.

If the `tinyhat_codex_auth` tool is unavailable, start the installed flow
yourself only after the user confirms the ChatGPT setting is on. Prefer
invoking the installed quick command directly if your interface supports
that. Otherwise run the same installed runtime helper:

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
- Do not start the helper until the user confirms the ChatGPT Security
  toggle is on.
- Do not paste the raw auth URL or duplicate the device code unless the
  helper explicitly reports that Telegram delivery failed.
- The device code is copyable but temporary. It is not the OAuth token.
- If the user says they signed in, use `/codex_auth_status` to verify.
- If they ask about remaining limits, use `/codex_limits`.
- If the flow fails or seems stuck, use `/codex_auth_log` and surface the
  bounded non-secret error. Do not guess.

## Helpful Copy

After sending the prerequisite screenshot, a good short reply is:

```text
I sent the ChatGPT setting screenshot. Please turn on "Enable device code
authorization for Codex" in Settings > Security, then reply here when it
is on. I will start the sign-in after that.
```

After the user confirms and the auth flow starts, a good short reply is:

```text
I started the OpenAI Codex sign-in flow. Tap the authorization button I
sent above, then paste the code from the next message. I will switch to
your Codex subscription when OpenAI finishes the sign-in.
```
