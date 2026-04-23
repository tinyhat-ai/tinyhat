# Tinyhat

**Observability and optimization for AI skills.**

Tinyhat is a Claude Code plugin that scans the Claude data already on your machine and produces one markdown report and one HTML snapshot about which skills you're actually using, which look dormant, and what's worth creating next. The editorial framing in the report is written by the Claude agent at runtime — so the report reflects *your* week, not a canned template.

## Status

Early v0. Local-only, read-only. No hooks, no daemons, no network calls.

See the [v0 scope issue](https://github.com/tinyhat-ai/tinyhat/issues/1) for what's in and out.

## What you need

- Claude Code (CLI or desktop-app Code tab), version that supports plugins
- Python 3.8+ on your `PATH` (macOS and most Linux distros ship this by default; Windows users install from [python.org](https://www.python.org/))
- macOS for Cowork and desktop-app Code-tab surfaces. Linux/Windows will still get a scan of `~/.claude/projects/` but skip the desktop-app-specific paths silently.

## Install

### Option A — `--plugin-dir` (for local development or one-off use)

Clone this repo and start Claude Code with the plugin loaded:

```bash
git clone https://github.com/tinyhat-ai/tinyhat.git
cd tinyhat
claude --plugin-dir "$(pwd)"
```

### Option B — install from git (permanent)

Inside Claude Code, use the plugin manager:

```text
/plugin install https://github.com/tinyhat-ai/tinyhat.git
```

## Usage

Inside Claude Code, either say what you want in natural language or call the skill directly:

- *"Which skills am I actually using?"* / *"Review my skill usage."* / *"Open my Tinyhat report."*
- `/tinyhat:review` — produce a fresh report and open the HTML
- `/tinyhat:review --archive` — also write today's dated archive snapshot
- `/tinyhat:review --no-open` — skip opening the browser (used by the daily auto-run)
- `/tinyhat:review routine on` / `off` / `status` — manage the once-per-day adaptive refresh
- `/tinyhat:review where` — print the paths Tinyhat reads and writes
- `/tinyhat:review clear-archive` — delete all dated snapshots (keeps `latest/`)

Output lives under `~/.claude/tinyhat/`:

```
~/.claude/tinyhat/
├── routine.json
├── latest/{report.md, report.html, run-stamp.txt}
├── archive/YYYY-MM-DD/{report.md, report.html}   (up to 31 dated dirs)
└── feedback.jsonl
```

Everything under that directory is safe to delete — the plugin recreates it on next run.

## Daily adaptive refresh

Tinyhat's routine is *opportunistic*, not cron-driven: at most once per local calendar date, the skill checks on load whether a snapshot should fire and runs it quietly in the background. No launchd, no cron. If your laptop is closed at midnight, no snapshots are missed — the next one fires the first time you actually use Claude Code that day.

Toggle with `/tinyhat:review routine off` / `on`. Default is on.

## How attribution works

Tinyhat reads transcripts from `~/.claude/projects/**/*.jsonl` (and Cowork equivalents on macOS) and attributes a skill invocation when it sees any of:

- a `Skill` tool call (`{"name":"Skill","input":{"skill":"<name>"}}`)
- a `Read` on `.../skills/<name>/SKILL.md` that is followed by another tool call in the same turn (bare reads are dropped as likely false positives)
- a user turn containing `<command-name>/<name></command-name>`

Names are cross-checked against the local skill inventory (`~/.claude/skills/`, project-local `.claude/skills/`, `~/.claude/plugins/**/skills/*/SKILL.md`, Cowork bundles on macOS). Unknown names go to the audit trail; they do not appear in the ranking.

## Architecture

```
┌──────────────────────────┐    ┌─────────────────────┐    ┌────────────────────────┐
│  gather_snapshot.py      │    │  agent writes       │    │  render_report.py      │
│  scans local transcripts ├───▶│  tinyhat-analysis   ├───▶│  merges snapshot +     │
│  → tinyhat-snapshot.json │    │  .json (in-session) │    │  analysis → report.*   │
└──────────────────────────┘    └─────────────────────┘    └────────────────────────┘
```

The Python helper does only data gathering (no judgement). The Claude agent reads the snapshot and writes the editorial layer (headline, what stands out, recommendations). The renderer merges both into one markdown and one self-contained HTML file.

## Layout

```
tinyhat/
├── .claude-plugin/plugin.json
├── skills/
│   └── review/
│       ├── SKILL.md
│       ├── references/writing-the-analysis.md
│       └── templates/
│           ├── report.html.tmpl
│           ├── report.md.tmpl
│           └── report.css
├── scripts/
│   ├── gather_snapshot.py
│   ├── render_report.py
│   └── routine.py
└── README.md
```

## Why "Tinyhat"?

I keep coming back to the way humans swap roles: "put on your marketing hat." I wonder if AI agents will land there too — a role, a hat, the skills that come with it. Tinyhat is the observability for those skills, so a team can see what's used, what it costs, and what's worth keeping.

## Contributing

Fork, branch, open a PR against `main`. Use [Conventional Commits](https://www.conventionalcommits.org) for the subject if you can. That's the short version — see [AGENTS.md](AGENTS.md) if you want the details, or if you're an AI agent contributing under a bot identity.

## License

MIT. See [LICENSE](LICENSE).
