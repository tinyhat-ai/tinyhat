---
name: tinyhat-slack
description: Connect the current Tinyhat-managed Hermes agent to a user's Slack workspace without SSH, public ingress, or sharing Slack messages or token plaintext with Tinyhat.
---

# Tinyhat Slack

Use `tinyhat_slack_connect` when the user asks to connect this agent to Slack.

The tool sends the user:

- Hermes' current Slack Agent-view manifest;
- a highlighted Slack create-app screenshot and button;
- one secure Mini App form for the bot token, Socket Mode app token, and
  allowed Slack member IDs.

The Mini App encrypts all values for this Computer. Tinyhat carries only
ciphertext and safe connection metadata. Hermes validates and saves the values
locally, then owns the Slack Socket Mode connection and all Slack functionality.

Call the tool once with no arguments. Do not ask for token values in chat, do
not substitute the generic private-secret flow, and do not send an extra reply
after the tool returns.
