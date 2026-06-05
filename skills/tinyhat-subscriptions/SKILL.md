---
name: tinyhat-subscriptions
description: Connect this OpenClaw Computer to the user's own ChatGPT subscription via device-code OAuth, or revert to platform-funded credits. Use when the user asks to use, connect, link, switch to, fund with, run on, or hook up their own ChatGPT plan, ChatGPT subscription, ChatGPT Plus / Pro / Team / Business, GPT subscription, paid ChatGPT account, or "my own LLM plan" — or to switch back to platform credits, Tinyhat credits, or the funded path.
---

# Tinyhat Subscriptions

Use Tinyhat subscription capabilities when the user wants this Computer
to run on the **user's own ChatGPT subscription** instead of the
Tinyhat-funded platform credits, or to revert.

The user's OAuth token is **born on the Computer** (via OpenClaw's
device-code login) and never reaches the agent, the chat, or the
Tinyhat backend. The only user-facing strings during linking are the
OpenAI verification URL (`auth.openai.com`) and a short device code.

## Route User Intent

| User ask | Operation / tool |
| --- | --- |
| First-time ask about connecting ChatGPT, "how do I connect", or the link failed because device-code is disabled | `subscriptions.open_prerequisite_help` / `tinyhat_open_chatgpt_subscription_prerequisite_help` |
| Connect, link, sign in with, switch to my own ChatGPT subscription / plan / Pro / Plus / Team / Business (after the prerequisite is on) | `subscriptions.open_link` / `tinyhat_open_chatgpt_subscription_link` |
| Revert, switch back, stop using my plan, go back to Tinyhat credits / platform credits / free / funded | `subscriptions.revert_to_platform_credits` / `tinyhat_revert_to_platform_credits` |

## Prerequisite — enable device code authorization in ChatGPT

Before the user can link their subscription, **they must enable
device-code authorization in their ChatGPT security settings**. This
is OpenAI's standing requirement for headless device-code sign-in
flows; without it the linking attempt fails with a clear non-secret
error and the user has to enable the setting and retry.

When the user first asks to connect their ChatGPT subscription:

1. **Call `tinyhat_open_chatgpt_subscription_prerequisite_help` first.**
   The tool sends the canonical settings screenshot directly to the
   user via Telegram (`photo_delivered: true`) and returns the
   walkthrough text — do not re-send the photo, do not paste the
   image URL into chat, and do not describe the screenshot as if the
   user might not have seen it. Forward the walkthrough text on its
   own via `reply_via_telegram`, acknowledging briefly that you've
   shared the screenshot above.
2. The steps the user has to follow on their end:
   - Open `chatgpt.com` → Settings → Security.
   - Scroll to **Secure sign in with ChatGPT**.
   - Toggle on **Enable device code authorization for Codex**.
   - Personal accounts can flip the toggle directly. Team / Business
     / Enterprise: workspace-admin-only — if it's greyed out, ask the
     workspace admin to enable it.

The canonical screenshot in this repo (for your reference only — the
plugin's prerequisite-help tool is what sends it to the user; never
paste this asset path into chat):

![ChatGPT Security settings — Enable device code authorization for Codex](assets/chatgpt-enable-device-code-for-codex.png)

Only ask the user to confirm they've enabled it before calling
`tinyhat_open_chatgpt_subscription_link`. If they haven't, the
linking attempt will fail with a message like *"device-code login is
disabled on your ChatGPT account — see your ChatGPT security
settings to enable it"*; surface that verbatim and, on the failure
path, call `tinyhat_open_chatgpt_subscription_prerequisite_help`
again so the user sees the screenshot inline rather than just the
error text.

## Link The Subscription

1. Confirm the user has enabled the device-code toggle above (one
   sentence: *"have you turned on Enable device code authorization
   for Codex in your ChatGPT security settings? If yes, I'll start
   the link."*).
2. Call `tinyhat_open_chatgpt_subscription_link`. The tool asks the
   platform to start a device-code session for this Computer; the
   Computer's runtime supervisor runs
   `openclaw models auth login --provider openai --device-code`
   (the supervisor owns the subprocess so this plugin stays
   subprocess-free per OpenClaw's plugin-install policy) and reports
   the verification URL + 9-character user code back to the platform.
   The tool polls until those values arrive (typically a few
   seconds) and returns them.
3. The tool sends two Telegram messages directly to the user before
   it returns control: first a message with the inline-keyboard URL
   button pointing at `auth.openai.com` (`delivered: true`), then a
   second bare-text bubble containing **only** the 9-character device
   code (`code_delivered: true`). The bare bubble is intentional —
   it lets the user long-press → Copy on mobile to grab only the
   code without dragging a selection across surrounding sentence
   text. Do not re-paste the device code in your own free-text
   reply, do not re-render the URL button, and do not paste any raw
   URL into chat. The verification URL is the v0.5 "no raw URLs in
   chat" exemption and stays inside the inline-keyboard button only;
   never invent or paste a raw Mini App URL into chat — Mini App
   launches are button-only as a separate rule.
4. Acknowledge briefly: *"started — tap “Sign in to ChatGPT” above,
   then paste the code from the next message on the device you're
   signed in to. The code expires in about 15 minutes."*
5. The Computer's supervisor detects the new auth-profile on its
   next tick and rewrites `openclaw.json` so subsequent agent turns
   select the `openai` OAuth profile and route through
   `openai/gpt-5.5` via the native Codex runtime. The first agent
   reply after that switch confirms it — no polling,
   no separate notification flow.

## Subscription Button Contract

- Treat `text` as the user-facing copy.
- If `delivered: true` is present, the plugin has already sent the
  native Telegram URL button. Acknowledge briefly only if needed;
  do not send a duplicate button.
- If `code_delivered: true` is present (link tool path), the
  9-character device code has already been sent as its own bare
  Telegram message bubble. Do not re-paste the code in your
  follow-up reply. If `code_delivered: false` is present, the bare
  bubble failed to send — paste the device code from the `user_code`
  field in your reply so the user still receives it (the code is the
  one paste-able non-secret value in this flow).
- If `delivered: false` is present on the link result, the sign-in
  button could not be delivered — tell the user the link couldn't
  start and ask them to retry; never paste the verification URL.
- If `photo_delivered: true` is present (prerequisite-help tool
  path), the canonical settings screenshot has already been sent to
  the user via Telegram. Do not re-send the photo, do not paste the
  image URL into chat, and do not describe the screenshot as if the
  user might not have seen it. If `photo_delivered: false` is
  present, the screenshot failed to send — do not claim a screenshot
  was shown; walk the user through the toggle in words instead.
- Treat `channelData.telegram.buttons` and
  `channelData.telegram.photo_url` / `photo_caption` /
  `followup_text` as transport-only payloads. Preserve them for
  Telegram rendering, but never quote or summarize any transport URL
  **other than the OpenAI verification URL** (the one exemption).
- The 9-character device code is the **only** paste-able non-secret
  string the user is asked to handle. Never reuse a captured code
  for a second user — codes are single-use, single-session.
- Never paste the OAuth token (the supervisor never returns it; if
  any tool result claims to carry one, treat it as a regression and
  refuse to surface it).
- If the tool returns `unsupported_channel_text`, use that copy
  when the current channel cannot render the Telegram URL button.

## Revert To Platform Credits

1. Call `tinyhat_revert_to_platform_credits`. The tool tells the
   platform to flip this Computer back to Tinyhat-funded credits
   and bumps the supervisor's config revision; the supervisor's
   next apply tick wipes the per-agent OAuth credential on disk and
   rewrites `openclaw.json` back to the OpenRouter / platform-credit
   route.
2. The first agent turn after the supervisor reapplies is back on
   platform-funded credits.
3. Confirm to the user: *"done — you're now back on Tinyhat-funded
   credits. Your ChatGPT subscription is no longer linked to this
   Computer."*
4. If the user asks where the OAuth token went, explain truthfully:
   it was deleted from this Computer's local auth store; the
   platform never had it.

## Failure Messages

Surface the platform's non-secret error verbatim when it appears.
Common cases:

| Reported reason | Explain |
| --- | --- |
| `device-code login disabled on your ChatGPT account` | Walk through the security-settings prerequisite again. |
| Device code expired (15-minute window) | Offer to start a fresh link with `tinyhat_open_chatgpt_subscription_link`. |
| OpenAI provider error | Surface the message; offer a retry. |
| Network / heartbeat timeout | Tell the user the link will retry on the next supervisor tick; no action needed from them. |

Never invent a failure mode the platform did not report. If the
status surface is unavailable, say so and stop guessing.

## Do Not

- **Never ask the user to paste a secret value in chat.** The 9-character
  device code is intentionally non-secret (paste-able by design); OAuth
  tokens, refresh tokens, `auth.json` contents, API keys, passwords,
  and account ids are secret values and must never enter the chat
  surface — not in messages, not in tool inputs, not in tool outputs.
- Do not ask the user for their ChatGPT password, OAuth token,
  `auth.json` contents, refresh token, API key, account id, or any
  other credential material in chat or via any tool input.
- Do not paste the OpenAI verification URL into a code block or
  raw text; render it as a Telegram URL button so the user can tap
  it directly.
- Do not share the 9-character device code across users or sessions.
- Do not link the same ChatGPT subscription to more than one
  Computer at a time (OpenAI's terms forbid account-credential
  sharing, and OpenClaw's refresh token rotates per-machine —
  sharing self-destructs technically as well as legally).
- Do not promise the user that the link survives if they recycle or
  reassign the Computer — by design, reassignment / recycling
  wipes the auth store on the Computer.
