---
name: tinyhat-runtime-status
description: Explain Tinyhat runtime status, environment facts, and restart or reload boundaries. Use when the user asks what this OpenClaw Computer is running on, whether Tinyhat is installed, what can be restarted or reloaded, or why a platform action is unavailable.
---

# Tinyhat Runtime Status

Use runtime status guidance when the user is asking about where the
agent is running, what Tinyhat exposes, or whether the agent can restart
or reload platform-managed components.

## Route User Intent

| User ask | Operation / tool |
| --- | --- |
| What am I running on, what is Tinyhat, is this managed by Tinyhat | `computer.status` / `tinyhat_get_platform_status` |
| Is a capability available, why is a button/tool missing | `computer.status` / `tinyhat_get_platform_status` |
| Update, upgrade, or roll back platform software | route to `tinyhat-software-updates` |
| Restart, reload, apply config, or reboot platform runtime | explain the boundary; do not invent a restart tool |

## Status Response

1. Call `tinyhat_get_platform_status`.
2. Summarize only secret-free platform facts: Computer identity label,
   runtime state, plugin version/ref, and capability availability.
3. If status includes capabilities, name the relevant operation and
   whether it is available.
4. Do not expose backend endpoints, metadata server details, bearer
   tokens, tenant ids, or private hostnames.
5. If the tool returns `action: "platform_auth_failure"`, use the
   returned `text` as the final user-facing guidance. Do not route to
   `tinyhat_report_problem`; the fallback already explains that normal
   platform reporting cannot authenticate.

## Restart Or Reload Boundary

- The v0.5 capability contract does not expose a generic agent-callable
  restart, reload, or reboot tool.
- Software updates are owner-initiated through the authenticated Mini
  App. Route update, upgrade, and rollback asks to
  `tinyhat-software-updates`.
- If the user wants to inspect or change platform settings, route to
  `tinyhat-computer-access` and open Manage Computer.
- If the user reports a broken runtime, route to `tinyhat-support-report`
  and call `tinyhat_report_problem`.
- If the user asks what Tinyhat installed, route to
  `tinyhat-package-inventory`.

## Safety Rules

- Never ask the user to paste a secret value in chat.
- Never print a raw Mini App URL, signed intent token, private backend
  URL, or Computer-private URL in user-facing text.
- Do not claim access to secret values, private URLs, or internal
  runtime controls.
- Prefer a clear boundary over an invented platform action.
- For `computer-auth: malformed_token`, direct the user only to
  `tinyhat.ai`, `support@tinyhat.ai`, or Telegram `@tinyhatchat`,
  and preserve the returned diagnostic handoff.
  Do not mention Discord, `support@tinyhat.com`, or slash-command
  support channels.
