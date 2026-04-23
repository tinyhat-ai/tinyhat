# Tinyhat

**The improvement loop for your Claude Code skills.**

[![CI](https://github.com/tinyhat-ai/tinyhat/actions/workflows/ci.yml/badge.svg)](https://github.com/tinyhat-ai/tinyhat/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/github/v/tag/tinyhat-ai/tinyhat?label=version&sort=semver)](https://github.com/tinyhat-ai/tinyhat/releases)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-blue.svg)](https://www.conventionalcommits.org)

Tinyhat is a Claude Code plugin built around a simple loop: **create what you use, retire what you don't, share what works.**

Other tools hand you a pre-built skill library.
Tinyhat bets the opposite way — a skill shaped by your real work beats any starter skill copied from elsewhere.
The first version of a skill isn't the product; the loop is.

To close the loop, Tinyhat scans your local Claude Code data and produces a short, read-only report of what's getting used, what looks dormant, and what's worth creating or retiring next.
The editorial framing is written by the Claude agent at runtime, so the report reflects *your* week, not a canned template.
Team skill-sharing follows naturally once the individual loop is working.

Everything runs locally. No hooks, no daemons, no network calls.

## Why "Tinyhat"?

I keep coming back to the way humans swap roles: *"put on your marketing hat."* I wonder if AI agents will land there too — a role, a hat, the skills that come with it. Tinyhat is the observability for those skills, so a team can see what's used and what's worth keeping.

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
