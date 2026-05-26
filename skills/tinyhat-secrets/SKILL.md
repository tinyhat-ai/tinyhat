---
name: tinyhat-secrets
description: Request and list Tinyhat runtime secret metadata. Use when the user asks to add, set, update, replace, configure, list, or manage a secret, API key, token, credential, env var, or runtime secret for this OpenClaw Computer.
---

# Tinyhat Secrets

Use Tinyhat secret capabilities when the user wants this Computer to
receive a runtime secret without exposing the secret value to the agent.

## Route User Intent

| User ask | Operation / tool |
| --- | --- |
| Add, set, update, replace, or configure one secret | `credentials.open_add_secret` / `tinyhat_request_runtime_secret` |
| List configured secret metadata | `credentials.list_metadata` / `tinyhat_list_runtime_secrets` |
| Open the secret manager from a slash-command surface | `/tinyhat_secrets manage` or `/tinyhat_secrets_manage` when available |

## Request A Secret

1. Infer a non-secret env-style name from the conversation, such as
   `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `DATABASE_URL`.
2. Infer a short non-secret description of why this Computer needs it.
3. If the name is ambiguous, ask for the name only. Do not ask for the
   value.
4. Call `tinyhat_request_runtime_secret` with `name` and `description`.
5. Render the returned Telegram button payload exactly as structured
   button transport when the channel supports buttons.
6. Tell the user that the value must be entered in Telegram, not chat.

## Secret Button Contract

- Treat `text` as the user-facing copy.
- Treat `channelData.telegram.buttons` as transport-only button data.
  Preserve it for Telegram rendering, but never quote or summarize any
  transport URL.
- Button-capable Telegram replies may intentionally omit `presentation`
  so the Telegram renderer can send native buttons without exposing
  transport URLs. If a fallback presentation exists, never invent a
  button from raw URL fields.
- If the tool returns `unsupported_channel_text`, use that copy when
  the current channel cannot render the Telegram Mini App button.
- Never copy Mini App link fields, button URL fields, signed link
  fields, private link fields, intent values, or tokens into
  user-facing text.

## List Secret Metadata

1. Call `tinyhat_list_runtime_secrets`.
2. Summarize names, descriptions, status, and revision information only.
3. If no secrets are configured, say that and offer to request a secret
   button for a named secret.

## Safe Degradation

- If the current channel cannot render the Telegram button, say the
  action must be retried from Telegram or Manage Computer.
- Never paste a raw Mini App URL as a fallback.
- Never claim that the agent can read, verify, echo, or migrate secret
  values directly.

## Safety Rules

- Never ask the user to paste a secret value in chat.
- Never print a raw Mini App URL, signed intent token, private backend
  URL, or Computer-private URL in user-facing text.
- Secret values are never returned by Tinyhat tools.
- Terminal commands and support summaries must not contain secret
  values.
