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

## Default Flow: Screenshot, Then `/codex_auth`

For common natural-language requests, call `tinyhat_codex_auth` once
with:

```json
{"action": "prerequisite"}
```

This sends the screenshot that shows where the ChatGPT Security setting
lives, with a short caption and the clickable `/codex_auth` command.
After the tool call, do not send an extra normal chat reply. The photo
caption is the user-facing reply.

The tool caption uses copy like this. Keep `/codex_auth` on its own line
so it is hard to miss:

```text
To use your Codex subscription here:

1. Open chatgpt.com > Settings > Security.
2. Turn on "Enable device code authorization for Codex".

Then come back here and tap:

/codex_auth
```

The tool sends this bundled screenshot with that caption:

```text
skills/tinyhat-codex-auth/assets/chatgpt-enable-device-code-for-codex.png
```

After this prerequisite tool returns, do not send a follow-up reply unless
Telegram delivery failed and the tool explicitly says a reply is needed.
Do not repeat the same link, and do not call the tool again.

The user must do this on their side:

1. Open `chatgpt.com`.
2. Go to Settings.
3. Open Security.
4. Scroll to **Secure sign in with ChatGPT**.
5. Turn on **Enable device code authorization for Codex**.

Personal accounts can usually turn this on directly. Team, Business, and
Enterprise accounts may require a workspace admin if the toggle is
disabled.

## Start Auth Only If The User Confirms In Chat

Normally the user starts auth by tapping `/codex_auth` in the Telegram
message. If instead the user replies in chat that the setting is already
enabled and asks you to continue, call `tinyhat_codex_auth` with:

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
- For the default flow, call `tinyhat_codex_auth` once with
  `{"action": "prerequisite"}`. Let the screenshot caption stand.
- Do not send an extra normal chat reply after the prerequisite tool.
- Do not call `tinyhat_codex_auth` twice during the same request.
- Do not start the helper until the user taps `/codex_auth` or explicitly
  confirms in chat that the ChatGPT Security toggle is on.
- Do not paste the raw auth URL or duplicate the device code unless the
  helper explicitly reports that Telegram delivery failed.
- The device code is copyable but temporary. It is not the OAuth token.
- If the user says they signed in, use `/codex_auth_status` to verify.
- If they ask about remaining limits, use `/codex_limits`.
- If the flow fails or seems stuck, use `/codex_auth_log` and surface the
  bounded non-secret error. Do not guess.

## Helpful Copy

The default screenshot caption should say:

```text
To use your Codex subscription here:

1. Open chatgpt.com > Settings > Security.
2. Turn on "Enable device code authorization for Codex".

Then come back here and tap:

/codex_auth
```

After the user confirms and the auth flow starts, a good short reply is:

```text
I started the OpenAI Codex sign-in flow. Tap the authorization button I
sent above, then paste the code from the next message. I will switch to
your Codex subscription when OpenAI finishes the sign-in.
```
