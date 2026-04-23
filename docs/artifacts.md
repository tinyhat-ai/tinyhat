# Artifacts — everything Tinyhat writes to your machine

Tinyhat is local-only and read-only against Claude's data. It writes files to **exactly one directory** plus transient temp files. Everything under these paths is safe to delete — the plugin recreates it on next run.

## Quick reference

| Path | What's there | When it's written |
|---|---|---|
| `~/.claude/tinyhat/routine.json` | Adaptive-daily on/off + install timestamp | On first run; overwritten on `/tinyhat:audit routine on|off` |
| `~/.claude/tinyhat/latest/report.html` | Latest report, self-contained HTML | Every `/tinyhat:audit` run |
| `~/.claude/tinyhat/latest/report.md` | Latest report, markdown mirror | Every `/tinyhat:audit` run |
| `~/.claude/tinyhat/latest/run-stamp.txt` | ISO local-date of last successful run | Every `/tinyhat:audit` run |
| `~/.claude/tinyhat/archive/YYYY-MM-DD/report.{html,md}` | Dated snapshot | When `--archive` is passed or the adaptive daily fires |
| `~/.claude/tinyhat/archive/index.html` | Browseable index of latest + all archives | Every render call |
| `~/.claude/tinyhat/feedback.jsonl` | Optional local feedback log (reserved) | Never in v0 (feedback goes via `mailto:`) |
| `<tempdir>/tinyhat-snapshot.json` | Transient data snapshot | Every `gather_snapshot.py` call |
| `<tempdir>/tinyhat-analysis.json` | Transient agent-authored analysis | Every `/tinyhat:audit` run |

`<tempdir>` is whatever `python3 -c 'import tempfile; print(tempfile.gettempdir())'` returns on your OS:
- macOS: `/var/folders/.../T/`
- Linux: `/tmp/`
- Windows: `%TEMP%`

## Directory layout

```
~/.claude/tinyhat/
├── routine.json
├── latest/
│   ├── report.html         ← open this to see the most recent report
│   ├── report.md
│   └── run-stamp.txt       ← one line: YYYY-MM-DD of the last run
└── archive/
    ├── index.html          ← open this to browse all reports
    ├── 2026-04-23/
    │   ├── report.html
    │   └── report.md
    ├── 2026-04-22/
    │   └── ...
    └── ...                 (up to 31 dated dirs; older pruned automatically)
```

## How to open each artifact

### The latest report

```bash
open ~/.claude/tinyhat/latest/report.html        # macOS
xdg-open ~/.claude/tinyhat/latest/report.html    # Linux
start ~/.claude/tinyhat/latest/report.html       # Windows
```

Or inside Claude Code: `/tinyhat:open`.

### The archive index (browse history)

```bash
open ~/.claude/tinyhat/archive/index.html
```

Or inside Claude Code: `/tinyhat:history`.

### A specific dated snapshot

```bash
open ~/.claude/tinyhat/archive/2026-04-23/report.html
```

The index page links to every dated snapshot — easier than typing.

### The markdown mirror (if you want to paste into a doc)

```bash
cat ~/.claude/tinyhat/latest/report.md
```

### The routine state

```bash
cat ~/.claude/tinyhat/routine.json
cat ~/.claude/tinyhat/latest/run-stamp.txt
```

Or inside Claude Code: `/tinyhat:audit routine status`.

### The raw snapshot JSON (for debugging attribution)

```bash
python3 -c 'import tempfile, pathlib; p = pathlib.Path(tempfile.gettempdir()) / "tinyhat-snapshot.json"; print(p)'
# copy that path and open it
```

Top-level keys: `meta`, `stats`, `inventory`, `top_skills`, `skill_counts`, `last_seen`, `sessions`, `events`, `events_audit`, `tool_totals`, `aggregate_tools`, `daily_rollups`, `dormant_by_origin`, `installed_by_origin`, `surface_rollups`, `coverage`. See [development.md](local-development.md) for the shape.

### The agent-authored analysis JSON (for debugging framing)

```bash
python3 -c 'import tempfile, pathlib; p = pathlib.Path(tempfile.gettempdir()) / "tinyhat-analysis.json"; print(p)'
```

Shape: `headline`, `headline_sub`, `what_stands_out[]`, `dormant_commentary`, `skill_recommendations[]`, `coverage_note`. Schema details in [`skills/audit/references/writing-the-analysis.md`](../skills/audit/references/writing-the-analysis.md).

## Retention

- `~/.claude/tinyhat/latest/` — always overwritten by the most recent run.
- `~/.claude/tinyhat/archive/` — keeps at most **31** dated directories. On every archive write, oldest directories are pruned. The index page always reflects what's currently on disk.

## Reset everything

If you want a clean slate:

```bash
rm -rf ~/.claude/tinyhat
rm -f "$(python3 -c 'import tempfile; print(tempfile.gettempdir())')"/tinyhat-*.json
```

The plugin rebuilds everything on the next `/tinyhat:audit`. Nothing else on your system is affected.

Or, less destructive — just clear the dated archives:

- `/tinyhat:audit clear-archive`

That removes every dir under `archive/` but keeps `latest/` and `routine.json`.

## What Tinyhat **reads** (never writes)

For transparency: the scanner only reads from these sources. It never modifies or deletes from them.

| Source | Purpose |
|---|---|
| `~/.claude/projects/**/*.jsonl` | Claude Code CLI + desktop-app Code-tab transcripts |
| `~/Library/Application Support/Claude/local-agent-mode-sessions/**/.claude/projects/**/*.jsonl` (macOS only) | Cowork transcripts |
| `~/Library/Application Support/Claude/claude-code-sessions/**/local_*.json` (macOS only) | Session wrappers for titles + surface classification |
| `~/.claude/skills/` | Your personal skill inventory |
| Project-local `.claude/skills/` | Project-scoped skills |
| `~/.claude/plugins/**/skills/*/SKILL.md` | Plugin-bundled skills |
| `~/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/**/skills/*/SKILL.md` (macOS only) | Cowork-bundled skills |
| `~/.gstack/analytics/skill-usage.jsonl` (optional) | Supporting telemetry if present |

The coverage note at the bottom of every report summarizes what was actually read on the run in question.
