---
name: tinyhat-slack
description: Disconnect a legacy Telegram-managed Slack connection. To connect any Computer to Slack, use tinyhat-connect-channel and tinyhat_channels instead.
---

# Legacy Slack disconnect

For every new Slack connection, use `tinyhat-connect-channel` and
`tinyhat_channels`. That flow works with or without Telegram. The registered
`tinyhat_slack_connect` tool is retained only for compatibility with earlier
Telegram-managed sessions; do not choose it for new channel setup.

Slack is a bundled provider connection, not a generic removable credential.
`tinyhat_credentials` must not be used for `SLACK_CONNECTION`,
`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, or `SLACK_ALLOWED_USERS`.
For a legacy Telegram-managed Slack bundle only, when the user asks to
disconnect, remove, or revoke Slack, call
`tinyhat_slack_disconnect` once with no arguments. The platform sends an
expiring two-stage Telegram confirmation. After final confirmation, the
detached plugin worker asks Slack to revoke the bot token and removes the
complete local Slack bundle together. The platform then uses its existing
generic Hermes restart path. Do not ask for text confirmation, expose a URL,
call `tinyhat_credentials`, or send an extra reply after the tool returns. A
transient revocation failure preserves the local bundle for retry; never claim
provider access was revoked from local deletion alone.

For a channel connected through `tinyhat_channels`, do not use the legacy
disconnect tool: it cannot remove the platform's saved channel binding. Explain
that this connection has no standalone disconnect operation yet. Do not delete
the Computer or revoke its Slack token as a workaround, and do not claim it was
disconnected. If the connection type is uncertain, check channel status first.
