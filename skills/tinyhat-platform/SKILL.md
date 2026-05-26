---
name: tinyhat-platform
description: Route Tinyhat platform capability requests from a managed OpenClaw Computer. Use when the user asks broadly about Tinyhat/OpenClaw platform actions, including secrets, Manage Computer, terminal access, runtime status, installed packages, restart or reload boundaries, or support reports.
---

# Tinyhat Platform Router

You are running inside a Tinyhat-managed OpenClaw Computer.
Use this router to choose the focused Tinyhat skill, then follow that
skill's instructions for the capability call and user-facing response.

## Route User Intent

| User ask | Focused skill | Operation / tool |
| --- | --- | --- |
| Add, set, replace, or configure a secret/API key/token | `tinyhat-secrets` | `credentials.open_add_secret` / `tinyhat_request_runtime_secret` |
| List configured secret metadata | `tinyhat-secrets` | `credentials.list_metadata` / `tinyhat_list_runtime_secrets` |
| Open or inspect Manage Computer | `tinyhat-computer-access` | `computer.open_manage` / `tinyhat_open_manage_computer_link` |
| Open a terminal or SSH-like shell | `tinyhat-computer-access` | `computer.open_terminal` / `tinyhat_open_terminal_link` |
| Ask what this agent is running on | `tinyhat-runtime-status` | `computer.status` / `tinyhat_get_platform_status` |
| Ask to restart, reload, update, or apply runtime config | `tinyhat-runtime-status` | explain the exposed boundary; do not invent a restart tool |
| Ask what Tinyhat installed | `tinyhat-package-inventory` | `packages.list_installed` / `tinyhat_list_installed_packages` |
| Report a Tinyhat/OpenClaw problem | `tinyhat-support-report` | `support.report_problem` / `tinyhat_report_problem` |

## Router Rules

- Prefer the focused skill whenever the request matches one row above.
- Use named operations or tools only; never construct platform URLs.
- If the user asks for a platform action not exposed by this contract,
  say that Tinyhat has not exposed that action to the agent yet.
- If the action needs user authentication, render the returned Telegram
  button payload when the channel supports buttons.
- If buttons are unavailable, say the action must be retried from
  Telegram or Manage Computer.

## Safety Rules

- Never ask the user to paste a secret value in chat.
- Never print a raw Mini App URL, signed intent token, private backend
  URL, or Computer-private URL in user-facing text.
- Secret metadata means names, descriptions, status, and revision
  information only.
  Secret values are never available through Tinyhat tools.
