# Architecture

The shape of Tinyhat's code and why each piece exists. For install and usage, see the [README](../README.md). For the dev loop, see [local-development.md](local-development.md).

## One-line summary

A Claude Code plugin where a Python script gathers facts, the Claude agent writes the editorial layer, and a second Python script renders a self-contained HTML report. No backend. No daemons. No network.

## Pipeline

```
┌────────────────────────┐   ┌──────────────────────┐   ┌─────────────────────────┐
│  gather_snapshot.py    │   │  tinyhat:audit │   │  render_report.py       │
│  local transcripts +   ├──▶│  agent writes the    ├──▶│  merges snapshot +      │
│  skill inventory       │   │  editorial layer     │   │  analysis → html + md   │
│  → snapshot.json       │   │  → analysis.json     │   │  → opens HTML           │
└────────────────────────┘   └──────────────────────┘   └─────────────────────────┘
                                                                     │
                                                                     ▼
                                                         ${CLAUDE_PLUGIN_DATA}/
                                                         ├── latest/
                                                         └── archive/YYYY-MM-DD/
                                                             └── index.html
```

The strict split is the point: a generic Python heuristic would always say the same thing about your data, which kills the report on re-read. Running this inside Claude Code means the agent gets to read *your* specific week and frame what's worth noticing. The data-gathering layer must stay heuristic-free so that editorial drift doesn't bleed into facts.

## Component-by-component

### `.claude-plugin/plugin.json`

Plugin manifest per Anthropic's convention. Name, version, description, author, homepage, repository, license, keywords. Skills are auto-discovered from `skills/*/SKILL.md` — they don't need to be listed here.

### `skills/audit/`

The primary skill (`tinyhat:audit`). Its `SKILL.md` is the agent entry point — frontmatter with natural-language triggers and `allowed-tools`, body with the step-by-step flow. Heavy detail for step 2 (writing `analysis.json`) lives in `references/writing-the-analysis.md` so the main `SKILL.md` stays under ~200 lines.

Templates live at `templates/`:

- `report.html.tmpl` — the HTML layout with `{{SLOT}}` placeholders.
- `report.md.tmpl` — the same report as markdown, optimized for terminal reading.
- `report.css` — extracted stylesheet, inlined at render time.

### `skills/open/`

Thin skill (`tinyhat:open`) — opens `${CLAUDE_PLUGIN_DATA}/latest/report.html`. No regeneration, no Python run. The point is to let the user revisit a report cheaply.

### `skills/history/`

Thin skill (`tinyhat:history`) — opens `${CLAUDE_PLUGIN_DATA}/archive/index.html`. Also cheap, also no regeneration. Regenerates just the index page if it's stale or missing.

### `scripts/gather_snapshot.py`

Facts-only scanner. Reads:
- `~/.claude/projects/**/*.jsonl` (CLI + desktop Code tab transcripts)
- `~/Library/Application Support/Claude/local-agent-mode-sessions/**/.claude/projects/**/*.jsonl` (Cowork, macOS only)
- `~/Library/Application Support/Claude/claude-code-sessions/**/local_*.json` (session wrappers)
- `~/.claude/skills/`, `~/.claude/plugins/**/skills/*/SKILL.md`, project-local `.claude/skills/`, Cowork skill bundles (inventory)
- `~/.gstack/analytics/skill-usage.jsonl` (optional cross-check)

Emits **two** JSON files alongside each other:

- `<tempdir>/tinyhat-snapshot.json` — compact, aggregate-only view for the agent's analysis step. Top-level keys: `meta`, `stats`, `top_skills`, `skill_counts`, `last_seen`, `dormant_by_origin`, `installed_by_origin`, `tool_totals`, `aggregate_tools`, `daily_rollups`, `surface_rollups`, `session_tool_patterns`, `events_audit`, `coverage`. Sized to fit in a single `Read` tool call on 100+ skill installations (see [#38](https://github.com/tinyhat-ai/tinyhat/issues/38)).
- `<tempdir>/tinyhat-snapshot-detail.json` — the full snapshot consumed by `render_report.py`. Superset of the compact view plus `inventory`, per-session `sessions`, raw `events`, and `events_audit.bare_read_skill_md`.

**Attribution rules** (per [`roadmap/v0/skill-attribution-from-transcripts.md`](../../Tinyhat%20Docs/roadmap/v0/skill-attribution-from-transcripts.md) in the private spec):

1. `Skill` tool_use → `input.skill` counts as one invocation.
2. `Read` on `.../skills/<name>/SKILL.md` counts **only if** another tool_use follows in the same turn (bare reads are kept in `events_audit.bare_read_skill_md` but dropped from the ranking — a v0 false-positive mitigation).
3. `<command-name>/<name></command-name>` in a user turn counts as one invocation.

Dedup: same session + same skill, ≤30s apart → one invocation. Unknown names not in the local inventory go to `events_audit.unknown_names`, never into the ranking.

**Cross-platform:** macOS-specific paths use `pathlib` + `is_dir()` checks; Linux and Windows skip them silently. The coverage note records what was and wasn't read.

### `scripts/render_report.py`

Pure templating. Takes:
- `--snapshot` (default `<tempdir>/tinyhat-snapshot-detail.json` — the renderer needs the full inventory, per-session rows, and raw events)
- `--analysis` (default `<tempdir>/tinyhat-analysis.json`)

If `analysis.json` is missing, fills in sensible but generic defaults derived from the snapshot. **This is a fallback — it's safe to run but dull to read.** Real value comes from the agent-written analysis.

Responsibilities:
- Renders `report.md` + `report.html`.
- Writes `${CLAUDE_PLUGIN_DATA}/latest/{report.md, report.html, run-stamp.txt}`.
- With `--archive`: also writes `${CLAUDE_PLUGIN_DATA}/archive/YYYY-MM-DD/` and prunes archive to ≤31 dirs.
- Always regenerates `${CLAUDE_PLUGIN_DATA}/archive/index.html` so the history page stays consistent.
- Builds the fallback `next_actions` list and the terminal-safe percentage strip used by `report.md`.
- With `--open`: uses `webbrowser.open()` (cross-platform).
- With `--index-only`: regenerates the index without re-rendering the report.

**Charts** are SVG generated in Python. No JS charting library; the HTML is genuinely self-contained and works offline.

**Client-side filtering** for the tools and sessions sections: `render_report.py` embeds a per-session payload as JSON; vanilla JS in the page recomputes totals, filters, and sort on change. Keeps the HTML single-file but interactive.

### `scripts/routine.py`

State for the adaptive daily refresh:

- `routine status` / `on` / `off` — reads/writes `${CLAUDE_PLUGIN_DATA}/routine.json`.
- `routine check` — exits 0 if a daily run **should** fire (enabled AND no run today). Exits non-zero otherwise. This is the trigger the main skill calls on every load.
- `where` — prints the full set of paths.
- `clear-archive` — removes every dated directory, keeps `latest/`.

Adaptive trigger semantics: at most one snapshot per local calendar date, fires on the first skill load that day. No launchd, no cron.

## Cross-cutting decisions

### Why Python stdlib only

- Pre-installed on macOS and most Linux.
- No pip install, no lock file, no `~/.venvs`.
- Matches Anthropic's own published example (`codebase-visualizer`) — skills that bundle scripts ship the scripts plain.

### Why self-contained HTML instead of a React app

- Zero install footprint on the user.
- Works offline, archivable, emailable.
- Editable in a plain editor without a build step.
- Anthropic's canonical skill-with-script pattern.

### Why the agent writes the analysis

The wedge: *"this report feels like it was written about my week, not about Claude Code in general."* That's only achievable if the reasoning happens inside a Claude session that has access to the snapshot. A Python heuristic can count; it can't say *"today is your first same-session multi-skill run."*

### Why namespaced skill names (`skill-audit`, not `audit`)

Skill dispatch across installed plugins is description-matched. Generic names like `audit` compete for intent with every other plugin's `audit-*` skills. Prefixing with the concrete noun (`skill-audit`, `open-latest-audit`, `audit-history`) keeps routing unambiguous even with many plugins installed.

### Why one-shot scripts instead of a daemon

- Matches the roadmap principle: *"local-only, no hooks, no daemons."*
- Simpler to reason about (no state between runs except the one file the script chooses to write).
- The adaptive daily is a skill-load check, not a background process.

## Where to read next

- [user-flows.md](user-flows.md) — what the user actually does
- [artifacts.md](artifacts.md) — every file Tinyhat writes, and where
- [local-development.md](local-development.md) — the dev loop
- `skills/audit/references/writing-the-analysis.md` — how the agent writes the analysis
