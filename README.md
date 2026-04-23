# Tinyhat

**Skill lifecycle observability for Claude Code.**

[![CI](https://github.com/tinyhat-ai/tinyhat/actions/workflows/ci.yml/badge.svg)](https://github.com/tinyhat-ai/tinyhat/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/github/v/tag/tinyhat-ai/tinyhat?label=version&sort=semver)](https://github.com/tinyhat-ai/tinyhat/releases)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-blue.svg)](https://www.conventionalcommits.org)

Tinyhat is a Claude Code plugin that scans the Claude data already on your machine and produces one markdown report and one self-contained HTML snapshot about which skills you're actually using, which look dormant, and what's worth creating next. The editorial framing is written by the Claude agent at runtime — so the report reflects *your* week, not a canned template.

Everything runs locally. No hooks. No daemons. No network calls. No account needed.

## Status

Early v0. Private beta. See the [v0 scope issue](https://github.com/tinyhat-ai/tinyhat/issues/1).

## What you need

- **Claude Code** — CLI or desktop-app Code tab, on a version that supports plugins (`/plugin` command available).
- **Python 3.9+** on your `PATH`. Pre-installed on macOS and most Linux; Windows users install from [python.org](https://www.python.org/).
- **macOS** for the richest experience (Cowork + desktop-app Code-tab surfaces both live there). Linux/Windows still get a full CLI scan of `~/.claude/projects/`; desktop-only paths are skipped silently.

## Install

Inside Claude Code, install straight from this GitHub repo:

```text
/plugin install tinyhat-ai/tinyhat
```

If that doesn't work on your version, use the git URL form:

```text
/plugin install https://github.com/tinyhat-ai/tinyhat.git
```

Then reload so the new skills register:

```text
/reload-plugins
```

That's it. The plugin auto-discovers its three skills under the `tinyhat:` namespace.

## Usage

Either ask in natural language or use the slash command.

### Produce a fresh report

- *"Audit my skills."* / *"Review my skill usage."* / *"Which skills should I remove?"* / *"Refresh my Tinyhat report."*
- `/tinyhat:skill-audit` — produce a fresh report and open the HTML
- `/tinyhat:skill-audit --archive` — also write today's dated archive snapshot
- `/tinyhat:skill-audit --no-open` — skip the browser (the adaptive daily run uses this)

### Open an existing report (no regenerate)

- *"Open my latest skill audit."* / *"Show me the last Tinyhat report."*
- `/tinyhat:open-latest-audit`

### Browse the history

- *"Show my skill-audit history."* / *"List all my Tinyhat reports."*
- `/tinyhat:audit-history` — opens the local index page with links to every dated snapshot (up to 31)

### Manage the adaptive daily refresh

Tinyhat refreshes at most once per local calendar date, triggered opportunistically the first time you use Claude Code that day (no launchd, no cron — closes-laptop-friendly).

- `/tinyhat:skill-audit routine status`
- `/tinyhat:skill-audit routine off` / `routine on`
- `/tinyhat:skill-audit where` — print the paths Tinyhat reads and writes
- `/tinyhat:skill-audit clear-archive` — delete every dated snapshot (keeps `latest/`)

## Where output lives

Everything under one directory, safe to delete — the plugin recreates it:

```
~/.claude/tinyhat/
├── routine.json
├── latest/
│   ├── report.md
│   ├── report.html
│   └── run-stamp.txt
├── archive/
│   ├── index.html                ← opened by /tinyhat:audit-history
│   └── YYYY-MM-DD/report.{md,html}   (up to 31 dated dirs)
└── feedback.jsonl                (if you ever use the in-app feedback)
```

## How attribution works

Tinyhat reads local transcripts from `~/.claude/projects/**/*.jsonl` (and the desktop-app equivalents on macOS: Cowork sessions, Code-tab session wrappers) and counts a skill as invoked when it sees any of:

- a `Skill` tool call (`{"name":"Skill","input":{"skill":"<name>"}}`)
- a `Read` on `.../skills/<name>/SKILL.md` followed by another tool call in the same turn (bare reads are dropped as likely false positives)
- a user turn containing `<command-name>/<name></command-name>`

Names are cross-checked against your local skill inventory (`~/.claude/skills/`, project-local `.claude/skills/`, `~/.claude/plugins/**/skills/*/SKILL.md`, Cowork bundles). Unknown names go to the audit trail, never into the ranking.

## Architecture

```
┌──────────────────────────┐   ┌──────────────────────┐   ┌────────────────────────┐
│  gather_snapshot.py      │   │  agent writes        │   │  render_report.py      │
│  scans local transcripts ├──▶│  tinyhat-analysis    ├──▶│  snapshot + analysis   │
│  → tinyhat-snapshot.json │   │  .json (in-session)  │   │  → report.md + .html   │
└──────────────────────────┘   └──────────────────────┘   └────────────────────────┘
```

The Python helper only gathers facts. The Claude agent reads the snapshot and writes the editorial layer. The renderer merges both into a single self-contained HTML file you can open, share, or archive. That split is why the report is worth re-reading: it reflects *your* data and *your* agent's reading of it.

## Documentation

- [docs/user-flows.md](docs/user-flows.md) — exactly how to use the plugin, step-by-step for each skill
- [docs/artifacts.md](docs/artifacts.md) — every file Tinyhat creates, where it lives, how to open it, how to reset
- [docs/architecture.md](docs/architecture.md) — how the code is laid out and why
- [docs/local-development.md](docs/local-development.md) — how to hack on Tinyhat (testing, iteration, reset)
- [skills/skill-audit/references/writing-the-analysis.md](skills/skill-audit/references/writing-the-analysis.md) — detailed guidance for the agent-authored analysis layer

## Why "Tinyhat"?

I keep coming back to the way humans swap roles: *"put on your marketing hat."* I wonder if AI agents will land there too — a role, a hat, the skills that come with it. Tinyhat is the observability for those skills, so a team can see what's used, what it costs, and what's worth keeping.

## Contributing

Fork, create a `feat/...` / `fix/...` / `docs/...` / `chore/...` branch, open a PR against `main`. Use [Conventional Commits](https://www.conventionalcommits.org) for the subject. Linear history — we squash or rebase, never merge-commit.

- **[CONTRIBUTING.md](CONTRIBUTING.md)** — full workflow, local dev, CI reproduction, DCO
- **[AGENTS.md](AGENTS.md)** — contribution policy, especially if an AI agent is contributing under a bot identity

## Community

- **[Code of Conduct](CODE_OF_CONDUCT.md)** — Contributor Covenant v2.1. By participating you agree to uphold it.
- **[Security policy](SECURITY.md)** — how to report a vulnerability privately. **Please do not open a public issue for security problems.**
- **Questions, bugs, feature ideas** — open an issue using one of the [issue templates](.github/ISSUE_TEMPLATE/).
- **General contact** — `tinyhat@tinyloop.co`.

## License

MIT. See [LICENSE](LICENSE).
