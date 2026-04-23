# Artifacts — everything Tinyhat writes to your machine

Tinyhat is local-only and read-only against Claude's data. It writes
files to **exactly one directory** plus transient temp files.
Inside Claude Code, that directory is `${CLAUDE_PLUGIN_DATA}`. For a
marketplace install of `tinyhat@tinyloop`, that usually resolves to
`~/.claude/plugins/data/tinyhat-tinyloop/`. Everything under these
paths is safe to delete — the plugin recreates it on next run.
In plain-shell examples below, replace `${CLAUDE_PLUGIN_DATA}` with the
resolved path if your shell does not already have that variable set.
Older Tinyhat builds wrote to `~/.claude/tinyhat/`; the next
write-capable command now migrates that legacy directory into the
plugin-data path automatically.

## Quick reference

| Path | What's there | When it's written |
|---|---|---|
| `${CLAUDE_PLUGIN_DATA}/routine.json` | Adaptive-daily on/off + install timestamp | On first run; overwritten on `/tinyhat:audit routine on|off` |
| `${CLAUDE_PLUGIN_DATA}/latest/report.html` | Latest report, self-contained HTML | Every `/tinyhat:audit` run |
| `${CLAUDE_PLUGIN_DATA}/latest/report.md` | Latest report, markdown mirror | Every `/tinyhat:audit` run |
| `${CLAUDE_PLUGIN_DATA}/latest/snapshot.json` | Durable data snapshot — the facts | Every `/tinyhat:audit` run |
| `${CLAUDE_PLUGIN_DATA}/latest/analysis.json` | Durable agent analysis — the editorial layer | Every `/tinyhat:audit` run |
| `${CLAUDE_PLUGIN_DATA}/latest/run-stamp.txt` | ISO local-date of last successful run | Every `/tinyhat:audit` run |
| `${CLAUDE_PLUGIN_DATA}/archive/YYYY-MM-DD/report.{html,md}` | Dated snapshot | When `--archive` is passed or the adaptive daily fires |
| `${CLAUDE_PLUGIN_DATA}/archive/YYYY-MM-DD/{snapshot,analysis}.json` | Dated JSONs alongside the HTML/MD | When `--archive` is passed or the adaptive daily fires |
| `${CLAUDE_PLUGIN_DATA}/archive/index.html` | Browseable index of latest + all archives | Every render call |
| `${CLAUDE_PLUGIN_DATA}/feedback.jsonl` | Optional local feedback log (reserved) | Never in v0 (feedback goes via `mailto:`) |
| `<tempdir>/tinyhat-snapshot.json` | Transient **compact** snapshot — agent-facing, single-`Read`-sized | Every `gather_snapshot.py` call |
| `<tempdir>/tinyhat-snapshot-detail.json` | Transient **detail** snapshot — full data, renderer-facing | Every `gather_snapshot.py` call |
| `<tempdir>/tinyhat-analysis.json` | Transient mirror of latest/analysis.json (pipeline hand-off) | Every `/tinyhat:audit` run |

`<tempdir>` is whatever `python3 -c 'import tempfile; print(tempfile.gettempdir())'` returns on your OS:
- macOS: `/var/folders/.../T/`
- Linux: `/tmp/`
- Windows: `%TEMP%`

## Directory layout

```
${CLAUDE_PLUGIN_DATA}/            (e.g. ~/.claude/plugins/data/tinyhat-tinyloop/)
├── routine.json
├── latest/
│   ├── report.html         ← open this to see the most recent report
│   ├── report.md
│   ├── snapshot.json       ← the facts the report was built from
│   ├── analysis.json       ← the agent's editorial layer
│   └── run-stamp.txt       ← one line: YYYY-MM-DD of the last run
└── archive/
    ├── index.html          ← open this to browse all reports
    ├── 2026-04-23/
    │   ├── report.html
    │   ├── report.md
    │   ├── snapshot.json
    │   └── analysis.json
    ├── 2026-04-22/
    │   └── ...
    └── ...                 (up to 31 dated dirs; older pruned automatically)
```

## How to open each artifact

### The latest report

```bash
open "${CLAUDE_PLUGIN_DATA}/latest/report.html"        # macOS
xdg-open "${CLAUDE_PLUGIN_DATA}/latest/report.html"    # Linux
start "${CLAUDE_PLUGIN_DATA}/latest/report.html"       # Windows
```

Or inside Claude Code: `/tinyhat:open`.

### The archive index (browse history)

```bash
open "${CLAUDE_PLUGIN_DATA}/archive/index.html"
```

Or inside Claude Code: `/tinyhat:history`.

### A specific dated snapshot

```bash
open "${CLAUDE_PLUGIN_DATA}/archive/2026-04-23/report.html"
```

The index page links to every dated snapshot — easier than typing.

### The markdown mirror (if you want to paste into a doc)

```bash
cat "${CLAUDE_PLUGIN_DATA}/latest/report.md"
```

### The routine state

```bash
cat "${CLAUDE_PLUGIN_DATA}/routine.json"
cat "${CLAUDE_PLUGIN_DATA}/latest/run-stamp.txt"
```

Or inside Claude Code: `/tinyhat:audit routine status`.

### The durable snapshot JSON (the facts)

```bash
cat "${CLAUDE_PLUGIN_DATA}/latest/snapshot.json"
```

Top-level keys: `meta`, `stats`, `inventory`, `top_skills`, `skill_counts`, `last_seen`, `sessions`, `events`, `events_audit`, `tool_totals`, `aggregate_tools`, `daily_rollups`, `dormant_by_origin`, `installed_by_origin`, `surface_rollups`, `coverage`. See [development.md](local-development.md) for the shape.

The renderer consumes the detail copy at `<tempdir>/tinyhat-snapshot-detail.json`; the alongside `<tempdir>/tinyhat-snapshot.json` is a compact, aggregate-only view written for the agent's analysis step (so it fits in a single `Read` call even on 100+ skill installations — see [#38](https://github.com/tinyhat-ai/tinyhat/issues/38)). Both are transient. The durable copy under `latest/snapshot.json` is the full data and is what you (or Claude, on a follow-up turn) should read when drilling in.

### The agent-authored analysis JSON (the editorial layer)

```bash
cat "${CLAUDE_PLUGIN_DATA}/latest/analysis.json"
```

Shape: `headline`, `headline_sub`, `what_stands_out[]`, `dormant_commentary`, `skill_recommendations[]`, `next_actions[]`, `coverage_note`. Schema details in [`skills/audit/references/writing-the-analysis.md`](../skills/audit/references/writing-the-analysis.md).

Same story as snapshot.json — there's a transient mirror under `<tempdir>/tinyhat-analysis.json`, but `latest/analysis.json` is the durable copy a follow-up question will read from.

## Retention

- `${CLAUDE_PLUGIN_DATA}/latest/` — always overwritten by the most recent run.
- `${CLAUDE_PLUGIN_DATA}/archive/` — keeps at most **31** dated directories. On every archive write, oldest directories are pruned. The index page always reflects what's currently on disk.

## Reset everything

If you want a clean slate:

```bash
rm -rf ~/.claude/plugins/data/tinyhat-tinyloop
rm -f "$(python3 -c 'import tempfile; print(tempfile.gettempdir())')"/tinyhat-*.json
```

The plugin rebuilds everything on the next `/tinyhat:audit`. Nothing else on your system is affected.

Or, less destructive — just clear the dated archives:

- `/tinyhat:audit clear-archive`

That removes every dir under `${CLAUDE_PLUGIN_DATA}/archive/` but keeps `latest/` and `routine.json`.

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
