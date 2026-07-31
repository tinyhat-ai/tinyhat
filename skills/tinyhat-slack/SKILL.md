---
name: tinyhat-slack
description: Connect or disconnect the current Tinyhat-managed Hermes agent from a user's Slack workspace without SSH, public ingress, or sharing Slack messages or token plaintext with Tinyhat.
---

# Tinyhat Slack

Use `tinyhat_slack_connect` when the user asks to connect this agent to Slack.

The tool sends the user:

- Hermes' current Slack Agent-view manifest;
- a highlighted Slack create-app screenshot and button;
- one secure Mini App form for the bot token, Socket Mode app token, and
  allowed Slack member IDs.

Before sending the manifest, Tinyhat removes Hermes slash-command definitions
and the `commands` OAuth scope. Slash-command names are workspace-global, so
per-agent commands would collide when a workspace connects more than one
Hermes agent. Agent messages, direct messages, mentions, invited channels,
files, and Socket Mode remain owned by Hermes.

The Mini App encrypts all values for this Computer. Tinyhat carries only
ciphertext and safe connection metadata. Hermes validates and saves the values
locally, then owns the Slack Socket Mode connection and all Slack functionality.
After submission, Hermes immediately acknowledges receipt in Telegram. It then
reports either the validation stage that failed or confirms that it sent the
first owner-DM message in Slack. The connection is not marked ready until that
Slack message succeeds. Tinyhat receives only the value-blind stage, stable
error code, field-presence booleans, allowed-member count, and validated
app/workspace labels; it never receives tokens or member IDs.

Call the tool once with no arguments. Do not ask for token values in chat, do
not substitute the generic private-secret flow, and do not send an extra reply
after the tool returns.

Slack is a bundled provider connection, not a generic removable credential.
`tinyhat_credentials` must not be used for `SLACK_CONNECTION`,
`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, or `SLACK_ALLOWED_USERS`.
When the user asks to disconnect, remove, or revoke Slack, call
`tinyhat_slack_disconnect` once with no arguments. The platform sends an
expiring two-stage Telegram confirmation. After final confirmation, the
detached plugin worker asks Slack to revoke the bot token and removes the
complete local Slack bundle together. The platform then uses its existing
generic Hermes restart path. Do not ask for text confirmation, expose a URL,
call `tinyhat_credentials`, or send an extra reply after the tool returns. A
transient revocation failure preserves the local bundle for retry; never claim
provider access was revoked from local deletion alone.
