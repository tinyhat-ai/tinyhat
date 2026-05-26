---
name: tinyhat-package-inventory
description: List and explain Tinyhat-installed and user-installed package inventory. Use when the user asks what Tinyhat installed, which plugins or default skills are present, what repo/ref is running, or how Tinyhat defaults differ from user-installed skills.
---

# Tinyhat Package Inventory

Use package inventory when the user asks what Tinyhat installed into
this OpenClaw Computer or how platform defaults differ from user-added
skills.

## Route User Intent

| User ask | Operation / tool |
| --- | --- |
| What did Tinyhat install, which plugin/ref is active | `packages.list_installed` / `tinyhat_list_installed_packages` |
| Which skills are Tinyhat defaults versus user-installed | `packages.list_installed` / `tinyhat_list_installed_packages` |

## Inventory Response

1. Call `tinyhat_list_installed_packages`.
2. Report Tinyhat-installed defaults separately from user-installed
   skills or packages.
3. For Tinyhat defaults, summarize public package refs, versions, SHAs,
   and named capabilities when present.
4. For user-installed items, summarize only the public names and refs
   the platform reports.
5. If the platform does not report a user-installed split yet, say that
   the current inventory does not distinguish user-installed skills.

## Boundaries

- Package inventory is for public refs, versions, SHAs, capability
  names, and safe install state.
- Do not infer private repository names, local checkout paths, or hidden
  deployment metadata.
- Do not treat package inventory as proof that a secret value exists;
  use `tinyhat-secrets` for secret metadata.

## Safety Rules

- Never ask the user to paste a secret value in chat.
- Never print a raw Mini App URL, signed intent token, private backend
  URL, or Computer-private URL in user-facing text.
- Do not expose private package URLs or internal environment details.
- Use named Tinyhat tools only.
