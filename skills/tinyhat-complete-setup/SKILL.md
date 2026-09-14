---
name: tinyhat-complete-setup
description: Finish a Tinyhat Computer's onboarding when the owner asks to set up their selected coding agent and Slack or Telegram, finish setup, or get their Computer ready to use. Coordinate channel setup and official provider login without changing ownership. Not for creating Hats, upgrading a service account, or changing an already-working model without a request.
---

# Finish Computer setup

Use the system and channel the owner already selected; ask only for missing
choices. The agent doing the setup can differ from the requested cloud system.
Keep three checks: Computer accessible, selected channel replies, selected
system signed in. Do not call the setup complete just because a VM is ready.

## Computer and channel

From the owner's laptop, follow https://tinyhat.ai/agents.md using its public
owner APIs and a token stored outside any project. Reuse the created Computer
and request key after uncertain responses. Never use admin/machine tokens on
the laptop. From an existing Computer, keep its current identity; do not create
a replacement to finish onboarding.

Load `tinyhat:tinyhat-connect-channel`. Use `tinyhat_channels` for status and
the selected Telegram/Slack setup. With permission, use the owner's signed-in
local app to create/install the bot. If the app is unavailable, send the
private setup link/QR so they can continue on another device. Telegram's
24-hour pairing link is different from a five-minute Tinyhat browser-login
link. Only a laptop agent with the owner API token can mint the latter; a
Computer agent shares its existing owner-aware Computer page instead and leaves
any required Tinyhat sign-in to the owner. Preserve the complete browser-link URL, including its fragment. Generate its QR
locally; never use a public QR service. If no local generator is available,
the private clickable link is sufficient.
Never encode Slack or model-provider credentials into links or QR codes. Poll status after the
handoff and verify an actual message and reply on this Computer.

For Slack, use its guided **From a manifest** flow with the Computer's exact
Agent-view JSON. Take only the two tokens from Slack's setup/token instructions
and submit them through the private encrypted form/file path. Hermes owns the
listener; do not scaffold another bot process. Never replace an owner allowlist
with a wildcard to make a test pass.

## System login

Tinyhat sign-in does not sign the owner into their model provider. Hermes's
messaging provider, the selected CLI, and its desktop app are separate checks.

- **ChatGPT (Codex):** open the Computer desktop. Run `codex login` in its
  terminal and complete the official browser flow on that Computer. Open the
  ChatGPT desktop app, select Codex, complete its sign-in and request a harmless
  response. Verify a CLI response separately.
- **Claude Code:** run `claude` in the Computer's terminal and complete its
  official login prompt. If the browser returns a code, enter it in that
  waiting terminal. Open Claude Desktop, select Code, sign in and verify a
  harmless response there and in the CLI.
- **Hermes:** verify a real response with the included model access. Do not
  require a Codex/Claude subscription. If the owner also asks to connect their
  ChatGPT subscription to Hermes, use `tinyhat:tinyhat-codex-auth` and verify
  Hermes after the supported activation flow; a CLI login alone is not proof.

Use the owner's provider email, asking if different from their Tinyhat email.
Read only the relevant code email when they authorized mailbox access; otherwise
ask for the code. Let them finish passwords, passkeys, MFA or challenges that
need their action. Never copy local auth files, browser profiles or refresh
tokens to another Computer. Do not ask for passwords or Slack tokens in chat.

Use the runtime's official Linux desktop apps. A browser tab is not a desktop
app. These apps require a compatible desktop-enabled runtime/image; older
Computers may have only the CLI. Report the needed runtime/image update when the
installer is absent. On a compatible runtime, an owner-authorized repair is
`PYTHONPATH=/opt/tinyhat-hermes-runtime python3 -m hermes_runtime.agent_desktops --install --system codex`
(use `--system claude_code` for Claude). This is an explicit remote-terminal
operation; it does not happen on heartbeat or silently authenticate the owner. Do not invent a GUI or use unofficial
repackaged applications. Report provider account/plan limitations precisely.

## Handoff

Send a unique harmless test message in the chosen channel and check the reply.
Ask it to create a small welcome note, then verify it in the Computer desktop
to establish that the chat is using this Computer. Return the private Computer
and chat links with the separate CLI/app results. Keep incomplete checks open
with the exact next action for the owner; resume after their approval.
