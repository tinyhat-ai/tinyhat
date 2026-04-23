# Tinyhat

**Skill lifecycle observability for Claude Code.**

[![CI](https://github.com/tinyhat-ai/tinyhat/actions/workflows/ci.yml/badge.svg)](https://github.com/tinyhat-ai/tinyhat/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/github/v/tag/tinyhat-ai/tinyhat?label=version&sort=semver)](https://github.com/tinyhat-ai/tinyhat/releases)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-blue.svg)](https://www.conventionalcommits.org)

Tinyhat is a Claude Code plugin that produces a local, read-only report about which skills you're actually using, which look dormant, and what to create next. The editorial framing is written by the Claude agent at runtime — so the report reflects *your* week, not a canned template.

Everything runs locally. No hooks, no daemons, no network calls.

## Why "Tinyhat"?

I keep coming back to the way humans swap roles: *"put on your marketing hat."* I wonder if AI agents will land there too — a role, a hat, the skills that come with it. Tinyhat is the observability for those skills, so a team can see what's used and what's worth keeping.

## Install

Inside Claude Code:

```text
/plugin install tinyhat-ai/tinyhat
/reload-plugins
```

Requires Python 3.9+ on your `PATH` (pre-installed on macOS and most Linux).

## Usage

Ask in plain English or use a slash command:

- **Produce a report:** *"Audit my skills."* · `/tinyhat:audit`
- **Re-open the last report:** *"Show my latest skill audit."* · `/tinyhat:open`
- **Browse history:** *"Show my skill-audit history."* · `/tinyhat:history`
- **Manage the daily routine:** *"Turn off tinyhat's daily run."* · `/tinyhat:routine status|on|off|where|clear`

Output lives at `~/.claude/tinyhat/latest/report.html`. For every flow, trigger, and sub-command, see [`docs/user-flows.md`](docs/user-flows.md).

## Documentation

Deeper docs live in [`docs/`](docs/):

- [`docs/user-flows.md`](docs/user-flows.md) — each skill, step by step
- [`docs/artifacts.md`](docs/artifacts.md) — every file Tinyhat writes, and how to open or reset it
- [`docs/architecture.md`](docs/architecture.md) — how the code is laid out
- [`docs/local-development.md`](docs/local-development.md) — how to hack on it

## Contributing

Fork, branch (`feat/...`, `fix/...`, `docs/...`, `chore/...`), open a PR. Use [Conventional Commits](https://www.conventionalcommits.org) for the subject. We squash-merge onto a linear `main`.

Full workflow: [CONTRIBUTING.md](CONTRIBUTING.md).

## Community

- [Code of Conduct](CODE_OF_CONDUCT.md) · [Security policy](SECURITY.md)
- Questions or ideas: open an issue. Private security reports: use GitHub's advisory flow or `security@tinyloop.co`.

## License

MIT. See [LICENSE](LICENSE).
