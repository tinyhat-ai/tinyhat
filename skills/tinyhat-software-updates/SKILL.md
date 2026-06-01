---
name: tinyhat-software-updates
description: Guide Tinyhat platform software updates and rollbacks. Use when the user asks to update, upgrade, roll back, downgrade, install the latest version, check for software updates, or refresh OpenClaw, the runtime, the Tinyhat plugin, default skills, or platform software on this Tinyhat-managed Computer.
---

# Tinyhat Software Updates

Use Software Updates when the owner wants this Computer's platform-managed
software to move to a newer release or roll back to an older published release.

## Route User Intent

| User ask | Operation / tool |
| --- | --- |
| Update, upgrade, install latest, check for updates | `computer.software_updates` / `tinyhat_open_software_updates_link` |
| Roll back, downgrade, pick an older release | `computer.software_updates` / `tinyhat_open_software_updates_link` |
| What versions are running before updating | `computer.status` / `tinyhat_get_platform_status`, then `computer.software_updates` if they want to act |

## Update Flow

1. If the user asks to update or roll back, call
   `tinyhat_open_software_updates_link`.
2. Render the returned Telegram button payload when buttons are
   supported.
3. Tell the user the Mini App is the authenticated place to choose the
   target release. They can select **Update to latest** or pick a
   published release for rollback.
4. Explain the update accurately: Tinyhat records the desired target,
   the Computer supervisor applies it on its next heartbeat, and the
   Computer reports the applied version back afterward.
5. Tell the user that the Computer is updated in place. It is not
   recreated, so local files, runtime secrets, terminal access, and
   any on-Computer ChatGPT subscription auth store remain on the
   Computer.

## Version Information

- The Software / Updates Mini App is the source of truth for available
  releases, latest markers, and rollback choices.
- The update covers the platform-owned components shown there:
  OpenClaw, the Tinyhat runtime supervisor, and the Tinyhat plugin /
  default skills.
- Do not invent a latest version, release date, changelog, or rollback
  target from memory. If the user wants exact availability, open the
  Software / Updates button so the catalog can answer.
- Do not say the update is complete until the status or Mini App shows
  the applied version. Before then, say it has been requested and will
  apply on the next heartbeat.

## Safe Degradation

- If the channel cannot render a Telegram button, say the user must
  retry from Telegram or open Manage Computer and tap Software.
- Do not paste a raw Mini App URL, even if a tool response contains one
  for transport.
- Do not claim the agent can update arbitrary user-installed packages;
  this flow is only for Tinyhat platform-owned components.

## Safety Rules

- Never ask the user to paste a secret value in chat.
- Never print a raw Mini App URL, signed intent token, private backend
  URL, or Computer-private URL in user-facing text.
- Use named Tinyhat tools only.
