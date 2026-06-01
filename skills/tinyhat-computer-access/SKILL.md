---
name: tinyhat-computer-access
description: Open authenticated Tinyhat Manage Computer, Software / Updates, and terminal access. Use when the user asks to manage, inspect, configure, administer, open software updates, or open a terminal or shell for this Tinyhat-managed OpenClaw Computer.
---

# Tinyhat Computer Access

Use Tinyhat Computer access capabilities when the user needs an
authenticated platform surface instead of an agent-written URL.

## Route User Intent

| User ask | Operation / tool |
| --- | --- |
| Open Manage Computer, inspect the Computer, manage settings | `computer.open_manage` / `tinyhat_open_manage_computer_link` |
| Open Software / Updates | `computer.software_updates` / `tinyhat_open_software_updates_link` |
| Open a terminal, shell, SSH-like session, or run one admin-reviewed command | `computer.open_terminal` / `tinyhat_open_terminal_link` |

## Manage Computer

1. Call `tinyhat_open_manage_computer_link`.
2. Render the returned Telegram button payload when buttons are
   supported.
3. Say that Manage Computer is the authenticated place to inspect or
   change platform settings.

## Software Updates

1. Call `tinyhat_open_software_updates_link`.
2. Render the returned Telegram button payload when buttons are
   supported.
3. Say that Software / Updates lets the owner choose latest or a
   published rollback release for Tinyhat platform-owned components.

## Terminal Access

1. If the user supplied a command, treat it as an admin-reviewed launch
   hint.
2. Do not put secret values into the command hint.
3. Call `tinyhat_open_terminal_link`, passing the command only when it
   is non-secret.
4. Render the returned Telegram button payload when buttons are
   supported.
5. Say that the terminal opens through Tinyhat authentication.

## Safe Degradation

- If the channel cannot render a Telegram button, say the user must
  retry from Telegram or Manage Computer.
- Do not invent a terminal route or platform page path.
- Do not paste a raw Mini App URL, even if a tool response contains one
  for transport.

## Safety Rules

- Never ask the user to paste a secret value in chat.
- Never print a raw Mini App URL, signed intent token, private backend
  URL, or Computer-private URL in user-facing text.
- Secret values are not terminal launch hints.
- Use named Tinyhat tools only.
