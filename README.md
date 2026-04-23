# Tinyhat

**See which skills are part of your workflow — and which ones you may be missing.**

[![CI](https://github.com/tinyhat-ai/tinyhat/actions/workflows/ci.yml/badge.svg)](https://github.com/tinyhat-ai/tinyhat/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/github/v/tag/tinyhat-ai/tinyhat?label=version&sort=semver)](https://github.com/tinyhat-ai/tinyhat/releases)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-blue.svg)](https://www.conventionalcommits.org)

Tinyhat is a small Claude Code plugin that looks at your recent usage and turns it into a report.

I built it because I wanted a more honest view of my setup: what I was actually using, what was just sitting there installed, and what kinds of work kept coming up without a fitting skill.

Instead of guessing what skills you need, you can start from your actual workflow.

That usually leads to three useful actions:
- improve the skills you already rely on
- remove unused skills
- create the skills you seem to be missing

Everything runs locally. No hooks, no daemons, no network calls.

![Top of a Tinyhat audit report asking "Which skills are actually earning their keep?" with two summary cards: 11% skill utilization — 14 of 122 installed skills had at least one run — and 31% of sessions with skills, meaning 18 of 58 recent sessions fired at least one skill.](docs/images/audit-summary.png)

*A local report built from your recent Claude Code usage, showing which skills seem active, which look unused, and where you may be missing a skill.*

## Why "Tinyhat"?

I kept coming back to the way people switch roles: "put on your marketing hat," "put on your ops hat."

This project started from wondering whether agents might work that way too: different hats, different skills, different ways of working.

Tinyhat is just a small tool to help make those skills easier to see.

## Install

Inside Claude Code, add the Tinyloop marketplace and install the plugin from it:

```text
/plugin marketplace add tinyhat-ai/tinyhat
/plugin install tinyhat@tinyloop
/reload-plugins
```

The first line registers Tinyloop's marketplace (this repo doubles as its own marketplace). The second installs the `tinyhat` plugin from it. After this, `/plugin marketplace update tinyloop` pulls newer versions.

If `/plugin update tinyhat@tinyloop` appears to leave Tinyhat on old
code, reinstall cleanly:

```text
/plugin remove tinyhat@tinyloop
/plugin install tinyhat@tinyloop
/reload-plugins
```

Requires Python 3.9+ on your `PATH` (pre-installed on macOS and most Linux).

## Usage

Ask in plain English or use a slash command:

- **Produce a report:** *"Audit my skills."* · `/tinyhat:audit`
- **Re-open the last report:** *"Show my latest skill audit."* · `/tinyhat:open`
- **Browse history:** *"Show my skill-audit history."* · `/tinyhat:history`
- **Manage the daily routine:** *"Turn off tinyhat's daily run."* · `/tinyhat:routine status|on|off|where|clear`

Tinyhat writes under Claude Code's per-plugin data directory. For a
marketplace install of `tinyhat@tinyloop`, the latest HTML typically
lands at `~/.claude/plugins/data/tinyhat-tinyloop/latest/report.html`.
If you're upgrading from an older Tinyhat, the next write-capable run
automatically migrates data from the legacy `~/.claude/tinyhat/`
directory.
For every flow, trigger, and sub-command, see
[`docs/user-flows.md`](docs/user-flows.md).

## Documentation

Deeper docs live in [`docs/`](docs/):

- [`docs/user-flows.md`](docs/user-flows.md) — each skill, step by step
- [`docs/artifacts.md`](docs/artifacts.md) — every file Tinyhat writes, and how to open or reset it
- [`docs/architecture.md`](docs/architecture.md) — how the code is laid out
- [`docs/local-development.md`](docs/local-development.md) — how to hack on it
- [`roadmap/`](roadmap/) — what's being built now, next, and later; open a PR to propose a priority change

## Contributing

Fork, branch (`feat/...`, `fix/...`, `docs/...`, `chore/...`), open a PR. Use [Conventional Commits](https://www.conventionalcommits.org) for the subject. We squash-merge onto a linear `main`.

Full workflow: [CONTRIBUTING.md](CONTRIBUTING.md).

## Community

- [Code of Conduct](CODE_OF_CONDUCT.md) · [Security policy](SECURITY.md)
- Questions or ideas: open an issue. Private security reports: use GitHub's advisory flow or `security@tinyloop.co`.

## License

MIT. See [LICENSE](LICENSE).
