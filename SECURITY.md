# Security policy

Thanks for taking the time to report a potential issue. We take every
report seriously.

## Please do not open a public issue

If you suspect Tinyhat has a security problem, **do not open a public
GitHub issue**. Public issues are visible to everyone and can put other
users at risk.

## How to report privately

Use either channel, whichever is easier for you:

1. **GitHub Private Vulnerability Reporting** — on this repo, go to the
   Security tab and click *Report a vulnerability*. This keeps the
   discussion private between you and the maintainer.
2. **Email** — `security@tinyloop.co`. If you'd like to encrypt the
   message, say so in your first note and we'll share a key.

In your report, please include (as much as you have):

- A short description of the issue.
- Steps to reproduce (command lines, example inputs, screenshots).
- The version / commit of Tinyhat you tested on.
- Your platform (macOS, Linux, Windows; Python version).
- Any suggested mitigation you've already considered.

## What happens next

| Step | Target |
|---|---|
| Acknowledgement of your report | within 3 business days |
| Initial assessment + first response | within 7 business days |
| Fix timeline agreed with reporter | case-by-case, typically within 30 days |
| Public disclosure (advisory + release) | after a fix ships, coordinated with reporter |

We'll credit reporters in the release notes unless you prefer to stay
anonymous.

## Supported versions

Tinyhat is in early v0 / private beta. Only the latest `main` and the
latest tagged release receive fixes.

| Version | Supported |
|---|:---:|
| `main` | ✅ |
| Latest release | ✅ |
| Previous releases | ❌ |

Once v1 ships, this table will be updated with a longer support window.

## Scope

In scope for this policy:

- The plugin scripts (`scripts/*.py`).
- The generated HTML report (could misrender malicious skill names, for
  example).
- Attribution logic that could mis-credit skills.
- Any path-traversal or file-overwrite concern with the artifacts Tinyhat
  writes under `~/.claude/tinyhat/`.

Out of scope:

- Vulnerabilities in Claude Code itself — report those to Anthropic.
- Vulnerabilities in dependencies — report upstream when possible; we'll
  accept downstream bump PRs.
- Issues requiring the attacker to already have write access to your
  `~/.claude/` directory.
