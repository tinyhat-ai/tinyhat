---
name: tinyhat-platform
description: Use Tinyhat platform capabilities from a managed OpenClaw Computer. Trigger when the user asks to add or manage secrets, open Manage Computer, open terminal access, check runtime status, list installed Tinyhat packages, ask what platform this agent runs on, or report a Tinyhat Computer problem.
---

# Tinyhat Platform

You are running inside a Tinyhat-managed OpenClaw Computer.
Use the named Tinyhat tools instead of inventing platform URLs or asking
the user to paste privileged data into chat.

## Route User Intent

| User ask | Use |
| --- | --- |
| Add, set, replace, or configure a secret/API key/token | `tinyhat_request_runtime_secret` |
| List configured secret metadata | `tinyhat_list_runtime_secrets` |
| Open or inspect Manage Computer | `tinyhat_open_manage_computer_link` |
| Open a terminal or SSH-like shell | `tinyhat_open_terminal_link` |
| Ask what this agent is running on | `tinyhat_get_platform_status` |
| Ask what Tinyhat installed | `tinyhat_list_installed_packages` |
| Report a Tinyhat/OpenClaw problem | `tinyhat_report_problem` |

## Safety Rules

- Never ask the user to paste a secret value in chat.
- Never print a raw Mini App URL, signed intent token, private backend
  URL, or Computer-private URL in user-facing text.
- For privileged actions, render the returned Telegram `web_app` button
  payload when the channel supports buttons.
- If the current channel cannot render a Telegram button, explain that
  the action must be retried from Telegram or Manage Computer.
- Terminal command text is only a launch hint for admin review.
  Do not include secret values in terminal commands.
- Secret metadata means names, descriptions, status, and revision
  information only.
  Secret values are never available through Tinyhat tools.

## First Response Patterns

For secret entry:

1. Infer a non-secret name and description from the conversation.
2. Call `tinyhat_request_runtime_secret`.
3. Present the Telegram Mini App button.
4. Say the value must be entered in Telegram, not chat.

For status or inventory:

1. Call the status or package tool.
2. Summarize only public package refs, versions, and safe runtime state.
3. Avoid raw backend endpoints and private URLs.

Focused default skills and the router expansion are tracked in
tinyhat-ai/tinyhat#94.
