---
name: tinyhat-support-report
description: Collect redacted Tinyhat/OpenClaw support context. Use when the user says the Tinyhat Computer, OpenClaw runtime, plugin capability, Telegram button, terminal, secret entry, status, or package inventory is broken or behaving unexpectedly.
---

# Tinyhat Support Report

Use support reports when the user is describing a Tinyhat/OpenClaw
problem and the agent needs redacted platform context.

## Route User Intent

| User ask | Operation / tool |
| --- | --- |
| Report a problem, bug, broken Computer, broken button, failed secret entry, failed terminal | `support.report_problem` / `tinyhat_report_problem` |
| Ask for diagnostics to send to Tinyhat support | `support.report_problem` / `tinyhat_report_problem` |

## Report Flow

1. If the problem summary is clear, use it directly.
2. If the summary is missing, ask for a short non-secret description of
   what failed and what the user expected.
3. Call `tinyhat_report_problem` with the non-secret summary.
4. Return the redacted support context and a concise explanation of what
   was captured.

## What To Capture In The Summary

- Which action failed: secret entry, Manage Computer, terminal, status,
  package inventory, or another capability.
- What the user saw in ordinary words, without signed links or tokens.
- Whether the current channel could render Telegram buttons.

## Safety Rules

- Never ask the user to paste a secret value in chat.
- Never print a raw Mini App URL, signed intent token, private backend
  URL, or Computer-private URL in user-facing text.
- Do not ask for bearer tokens, local files, tenant ids, or private
  deployment details.
- Redacted support context is safe to summarize; secret values are not
  available through Tinyhat tools.
