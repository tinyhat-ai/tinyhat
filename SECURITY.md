# Security Policy

Thanks for taking the time to report a potential issue. We take every
report seriously.

## Please Do Not Open A Public Issue

If you suspect Tinyhat has a security problem, do not open a public
GitHub issue. Public issues are visible to everyone and can put other
users at risk.

## How To Report Privately

Use either channel:

1. GitHub Private Vulnerability Reporting on this repo's Security tab.
2. Email `security@tinyloop.co`.

In your report, include as much as you can:

- A short description of the issue.
- Steps to reproduce.
- The Tinyhat version or commit tested.
- The OpenClaw/runtime version if known.
- Any logs or screenshots with secrets removed.
- Any mitigation you already considered.

## What Happens Next

| Step | Target |
| --- | --- |
| Acknowledgement | within 3 business days |
| Initial assessment | within 7 business days |
| Fix timeline | case-by-case, typically within 30 days |
| Public disclosure | after a fix ships, coordinated with reporter |

We'll credit reporters in release notes unless you prefer to stay
anonymous.

## Supported Versions

Tinyhat is pre-1.0. Only the latest `main` and latest tagged release
receive fixes.

| Version | Supported |
| --- | :---: |
| `main` | yes |
| Latest release | yes |
| Previous releases | no |

## Scope

In scope:

- `openclaw.plugin.json` and package metadata.
- OpenClaw tool plugin code under `src/`.
- Packaged skills under `skills/`.
- Secret-entry, Manage Computer, terminal-entry, status, inventory, and
  support-report capability behavior.
- Any path, token, signed URL, or secret leakage through public docs,
  skills, tool responses, or Telegram presentation.

Out of scope:

- Vulnerabilities in OpenClaw itself.
- Vulnerabilities in Tinyhat backend services that are not exposed by
  this plugin package.
- Vulnerabilities in upstream dependencies.
- Issues requiring the attacker to already control the user's Computer
  or repository checkout.
