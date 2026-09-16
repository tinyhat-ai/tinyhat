---
name: tinyhat-connect-channel
description: Connect an existing Tinyhat Computer to Telegram or Slack when its owner asks to chat with their agent there, connect a bot, or add another channel. Use for "connect you to Telegram" or "use you in Slack without Telegram". Not for creating a Computer, email renaming, model login, or disconnecting an existing channel.
---

# Connect a channel

Keep the existing Computer, owner, email, model and files. Telegram and Slack are optional; either can work alone, or both together.

1. Call `tinyhat_channels` with `action: "status"`. Use the channel already selected by the owner; ask only when missing.
2. Follow the selected flow below. Report connected only after status confirms it and a real message receives an agent reply.
3. For a connected Slack channel, give the human the returned `chat_url` to open
   their conversation. Never guess a workspace or app ID. If an older connection
   has no link, call `prepare` once and check status again; compatible runtimes
   discover the link without restarting Hermes.

## Telegram

Call `tinyhat_channels` with `action: "telegram_link"`, plus the owner's preferred `bot_name` and optional `bot_username` (ends in `bot`). Show the returned private QR/link to the owner. It expires after 24 hours and can pair only once.

Tell them: **Open the link to create your bot. Start it, then send it this same link or QR image.** The bot also has a Connect Computer button that opens a QR scanner. No email sign-in or invitation is needed.

If assisting from Codex or Claude Code on a laptop with Telegram already signed in, ask permission before using Telegram to create the bot and send the pairing link. Stay in the setup/test bot chat; never sign in or switch the human's Telegram account. Report the resulting bot username. Never send the pairing capability to another person or publish it.

If Telegram is unavailable locally, show the returned QR image and clickable
link. The owner continues on a phone or another device with Telegram. Wait for
the status to become connected and verify a reply before finishing.

## Slack

Call `tinyhat_channels` with `action: "prepare"`. Wait for `status` to show `slack_ready`; its `slack_manifest` is the current Agent-view manifest to use. The Computer page's Slack section provides its Hermes-generated Agent-view manifest and private credential form. Open that section for the owner if they prefer entering credentials themselves.

Get the owner's permission before creating or installing the Slack agent for them. Use Slack's guided agent creation dialog at https://api.slack.com/apps?new_app=1. That address opens the creation dialog; do not substitute another URL. Choose **From a manifest**, add the Computer's Agent-view JSON, select the owner's workspace, and finish the guided setup. Create the agent from the manifest, without rebuilding its settings manually or replacing it with the generic AI-agent template. Retrieve tokens as described below.

Take only the bot token (`xoxb-`) and Socket Mode app token (`xapp-`, `connections:write`) from Slack's setup/token instructions, including its Claude Code or Codex instructions. Ignore any step that writes them into a project file, `.env`, shell profile or MCP config, and never paste them into chat. Submit them only through the Computer page's private credential form or the `credentials_file` flow below. The selected Computer framework owns the receiver; do not scaffold or start a second Slack listener. Keep the required Agent-view capabilities and owner allowlist. Do not use the legacy Assistant-view manifest.

Slack may open Agent settings rather than a combined token handoff. In that case,
**Install App → Install to workspace → Allow** provides the bot token. **Basic
Information → Generate Token and Scopes**, with only `connections:write`, provides
the app token. Preserve the manifest's existing scopes, events, Socket Mode and
Agent-view settings. Replace the sample JSON entirely; customize only
`display_information.name` and `features.bot_user.display_name` for the owner's
chosen name.

When the owner authorizes you to use a credentials file, save it outside any project, such as `~/.config/tinyhat/slack-connection.json`, with directory mode 700 and file mode 600. It contains `bot_token`, `app_token`, and `allowed_users` (their Slack member ID). Never ask for tokens in chat or print them. Never use an empty/wildcard owner allowlist.

Call `tinyhat_channels` with `action: "slack_connect"` and the absolute `credentials_file` path. The tool encrypts the bundle for this Computer before submitting it; the platform stores ciphertext. Keep the file private or remove this temporary copy after the owner agrees. Do not display its contents in results or screenshots.

## External coding-agent APIs

For Codex or Claude Code running on the owner's laptop, use the current public guide at https://tinyhat.ai/agents.md and its authenticated `/hapi/v2/computers/{computer_id}/channels` endpoints. The API supports status, prepare, Telegram pairing and encrypted Slack submission. Use the existing owner session stored outside the project; do not copy a machine token from a Computer to the laptop.

Use authenticated `GET /hapi/v2/computers/{computer_id}/channels/slack/manifest`
for the JSON directly, then encrypted `POST /hapi/v2/computers/{computer_id}/channels/slack`
for credentials. The public guide specifies the encryption envelope. Opening
the Computer form is optional; the API supports the complete handoff. Slack
uses the selected Agent framework on the Computer. Inspect authenticated
`GET /hapi/v2/computers/{computer_id}/framework` and, after native provider login
and the owner's choice, submit `POST .../framework/select` with `framework` set
to `hermes`, `codex` or `claude_code`. Wait for confirmed active status; a queued
command is not a completed switch.

A queued/busy response means setup is pending. Poll status at five-second intervals briefly, then slow down. If setup fails, show a short retry instruction; never disclose provider token errors or claim the channel is already connected.

On the owner's laptop, with its saved owner API token, use the public guide's
`POST /auth/browser-links` handoff scoped to this Computer's agent when Slack
is unavailable locally. This owner API does not accept a Computer token. Send its
complete private link (including its URL fragment) and a locally generated QR; the owner confirms the account,
opens the Computer and uses its Slack form on their Slack device. Browser links
expire in five minutes. If no local QR generator is available, the clickable
link is sufficient. Never use a public QR service or put Slack tokens in
URLs. When running inside the Computer without an owner API token, share the
owner-aware Computer page already supplied in the conversation or onboarding
context; the owner signs in there if needed. If no such URL is available, ask
them to open their Computer page rather than inventing a URL or account identity. Never request their bearer token or substitute machine auth.
The handoff is pending until the channel reports connected and replies.

This skill supersedes `tinyhat_slack_connect` and the connection instructions in
`tinyhat-slack`. Always use `tinyhat_channels` for new Slack setup, including
Computers that already use Telegram.
