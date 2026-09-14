---
name: tinyhat-connect-channel
description: Connect an existing Tinyhat Computer to Telegram or Slack when its owner asks to chat with their agent there, connect a bot, or add another channel. Use for "connect you to Telegram" or "use you in Slack without Telegram". Not for creating a Computer, email renaming, model login, or disconnecting an existing channel.
---

# Connect a channel

Keep the existing Computer, owner, email, model and files. Telegram and Slack are optional; either can work alone, or both together.

1. Call `tinyhat_channels` with `action: "status"`. Ask which missing channel the owner wants.
2. Follow the selected flow below. Report connected only after status confirms it and a real message receives an agent reply.

## Telegram

Call `tinyhat_channels` with `action: "telegram_link"`, plus the owner's preferred `bot_name` and optional `bot_username` (ends in `bot`). Show the returned private QR/link to the owner. It expires after 24 hours and can pair only once.

Tell them: **Open the link to create your bot. Start it, then send it this same link or QR image.** The bot also has a Connect Computer button that opens a QR scanner. No email sign-in or invitation is needed.

If assisting from Codex or Claude Code on a laptop with Telegram already signed in, ask permission before using Telegram to create the bot and send the pairing link. Stay in the setup/test bot chat; never sign in or switch the human's Telegram account. Report the resulting bot username. Never send the pairing capability to another person or publish it.

## Slack

Call `tinyhat_channels` with `action: "prepare"`. Wait for `status` to show `slack_ready`; its `slack_manifest` is the current Agent-view manifest to use. The Computer page's Slack section provides its Hermes-generated Agent-view manifest and private credential form. Open that section for the owner if they prefer entering credentials themselves.

The owner creates a Slack **agent** from that manifest, installs it in their workspace, and creates an app token with `connections:write`. Keep the required Agent-view capabilities and owner allowlist. Do not use the legacy Assistant-view manifest.

When the owner authorizes you to use a credentials file, save it outside any project, such as `~/.config/tinyhat/slack-connection.json`, with directory mode 700 and file mode 600. It contains `bot_token`, `app_token`, and `allowed_users` (their Slack member ID). Never ask for tokens in chat or print them. Never use an empty/wildcard owner allowlist.

Call `tinyhat_channels` with `action: "slack_connect"` and the absolute `credentials_file` path. The tool encrypts the bundle for this Computer before submitting it; the platform stores ciphertext. Keep the file private or remove this temporary copy after the owner agrees. Do not display its contents in results or screenshots.

## External coding-agent APIs

For Codex or Claude Code running on the owner's laptop, use the current public guide at https://tinyhat.ai/agents.md and its authenticated `/hapi/v2/computers/{computer_id}/channels` endpoints. The API supports status, prepare, Telegram pairing and encrypted Slack submission. Use the existing owner session stored outside the project; do not copy a machine token from a Computer to the laptop.

A queued/busy response means setup is pending. Poll status at five-second intervals briefly, then slow down. If setup fails, show a short retry instruction; never disclose provider token errors or claim the channel is already connected.
