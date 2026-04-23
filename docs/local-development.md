# Local development

How to hack on Tinyhat without publishing anything. Everything below runs against your real local Claude data — there's no separate fixture or sandbox in v0 yet.

## Prerequisites

- Python 3.9+ on your `PATH`.
- A clone of this repo:
  ```bash
  git clone https://github.com/tinyhat-ai/tinyhat.git
  cd tinyhat
  ```
- Some Claude Code usage in the last 30 days, or the report will be empty-but-correct.

## Two ways to test

Pick the one that matches what you're doing:

1. **Full plugin test** — `--plugin-dir` loads this folder as a real plugin, with the `tinyhat:` namespace and `${CLAUDE_PLUGIN_ROOT}` resolved. Restart required. This is what you do before pushing to verify the install flow.
2. **Script-only iteration** — run `gather_snapshot.py` / `render_report.py` directly from the shell. No Claude involved. Fastest for UI/template/CSS changes.

There's also a **project-local test harness** that lives in `.claude/skills/`. It shadows the plugin skills so you can exercise `/skill-audit`, `/open-latest-audit`, and `/audit-history` in the current Claude Code session *without restart* — but it uses hardcoded absolute paths and only works on the maintainer's machine. It is deleted before the plugin ships. Don't rely on it for your own development.

---

## 1. Full plugin test (what you'd do before a PR)

This exercises the plugin exactly the way a user would, namespaced as `/tinyhat:audit` etc.

### Start a fresh Claude Code session with the plugin loaded

```bash
claude --plugin-dir /absolute/path/to/tinyhat
```

You can pass `--plugin-dir` multiple times if you're testing against other plugins in parallel.

### Exercise the three skills

Type these in Claude Code. Pick slash commands or natural language — both should work.

**Produce a fresh report (the primary flow):**

```text
/tinyhat:audit
```

or

```text
Audit my skills.
```

The agent will:
1. Run `gather_snapshot.py` → writes `<tempdir>/tinyhat-snapshot.json`.
2. Read the snapshot and write `<tempdir>/tinyhat-analysis.json` — this is the editorial layer. Watch its reasoning; that's where Tinyhat earns its keep.
3. Run `render_report.py --archive --open`.
4. Your browser should open `~/.claude/tinyhat/latest/report.html`.

**What to judge on the report:**
- Headline: *"You have N skills installed. You used M of them in the last 30 days."* — are N and M correct to your gut?
- Top skills list — anything you know you used missing? Anything sneaking in that you didn't use?
- `What stands out` bullets — do they feel specific to *this* week, or generic?
- Dormant section (click "Keep it simple" → "Data junkie mode" first) — origin breakdown reasonable?
- Mode switch (top-right): Keep it simple ↔ Data junkie
- Tools filter chips (Data junkie → "All tools used this period")
- Session timestamps: local time with time of day, not UTC

**Open the latest report without regenerating:**

```text
/tinyhat:open
```

Should open the existing `~/.claude/tinyhat/latest/report.html` in your browser — no Python run.

**Browse the archive:**

```text
/tinyhat:history
```

Should open `~/.claude/tinyhat/archive/index.html`. One entry per day you've run the audit, up to 31. The header inside each report has an `all reports →` link that returns to this index.

**Check / toggle the adaptive daily routine:**

```text
/tinyhat:audit routine status
/tinyhat:audit routine off
/tinyhat:audit routine on
```

**Print the paths Tinyhat reads and writes:**

```text
/tinyhat:audit where
```

### Iterate on changes

Edit files in the cloned repo, then inside Claude Code run:

```text
/reload-plugins
```

This re-reads `SKILL.md` files and re-registers the skills. Python scripts are re-executed on every invocation, so changes to `scripts/*.py` take effect on the next `/tinyhat:audit`. Template and CSS changes take effect on the next `render_report.py` run.

### Reset state between tests

Tinyhat's state is two things: the output directory and the temp files.

```bash
# Wipe everything the plugin has written:
rm -rf ~/.claude/tinyhat

# Wipe the transient snapshot + analysis so the next run starts clean:
rm -f "$(python3 -c 'import tempfile; print(tempfile.gettempdir())')/tinyhat-snapshot.json"
rm -f "$(python3 -c 'import tempfile; print(tempfile.gettempdir())')/tinyhat-analysis.json"
```

The plugin recreates `~/.claude/tinyhat/` on the next run. Nothing else on your system is touched.

---

## 2. Script-only iteration (fastest loop for HTML/CSS)

When you're fiddling with the report layout, skip Claude entirely. The agent analysis isn't the feedback loop you care about; the renderer is.

### Run the full pipeline against your real data

```bash
# Gather facts from local transcripts:
python3 scripts/gather_snapshot.py
# → writes <tempdir>/tinyhat-snapshot.json, prints the path to stderr

# Generate an analysis.json (the editorial layer).
# For fast iteration, skip this step — render_report.py has Python fallbacks
# that produce a generic-but-useful analysis. Only the agent should write
# non-generic analysis.

# Render the report and open the HTML:
python3 scripts/render_report.py --archive --open
# → writes ~/.claude/tinyhat/latest/report.{md,html}
# → writes ~/.claude/tinyhat/archive/YYYY-MM-DD/
# → regenerates ~/.claude/tinyhat/archive/index.html
# → opens the HTML in your default browser
```

### Just re-render without re-gathering

If you've edited CSS or the template, keep the snapshot and just re-render:

```bash
python3 scripts/render_report.py --open
```

That reuses `<tempdir>/tinyhat-snapshot.json` from the previous gather run.

### Test the archive index in isolation

```bash
python3 scripts/render_report.py --index-only
open ~/.claude/tinyhat/archive/index.html
```

### Test a custom analysis JSON

If you want to test a specific piece of editorial content (a particular headline, a dormant-commentary edge case), write it by hand:

```bash
cat > "$(python3 -c 'import tempfile; print(tempfile.gettempdir())')/tinyhat-analysis.json" <<'JSON'
{
  "headline": "You have 42 skills installed. You used 3 of them this week.",
  "headline_sub": "Testing edge-case copy.",
  "what_stands_out": ["Bullet A.", "Bullet B."],
  "dormant_commentary": "Most of your surface is dormant.",
  "skill_recommendations": [],
  "coverage_note": "Synthetic test run."
}
JSON

python3 scripts/render_report.py --open
```

Read `skills/audit/references/writing-the-analysis.md` for the full schema.

### Routine state

```bash
python3 scripts/routine.py status
python3 scripts/routine.py check   # exits 0 if a daily run should fire, non-zero otherwise
python3 scripts/routine.py on
python3 scripts/routine.py off
python3 scripts/routine.py where
python3 scripts/routine.py clear-archive
```

All of these accept `--home-root /some/path` if you want to test against a throwaway location instead of `~/.claude/tinyhat/`:

```bash
python3 scripts/routine.py --home-root /tmp/tinyhat-test status
python3 scripts/render_report.py --home-root /tmp/tinyhat-test --open
```

---

## 3. Where things live

```
tinyhat/
├── .claude-plugin/
│   └── plugin.json                  ← plugin manifest
├── skills/
│   ├── skill-audit/
│   │   ├── SKILL.md                 ← primary skill: produce the audit
│   │   ├── references/
│   │   │   └── writing-the-analysis.md   ← detailed agent guidance
│   │   └── templates/
│   │       ├── report.html.tmpl     ← HTML layout with {{SLOT}} placeholders
│   │       ├── report.md.tmpl       ← Markdown equivalent
│   │       └── report.css           ← extracted stylesheet (inlined at render)
│   ├── open-latest-audit/SKILL.md   ← opens latest without regenerating
│   └── audit-history/SKILL.md       ← opens the archive index
├── scripts/
│   ├── gather_snapshot.py           ← the data layer (no judgement)
│   ├── render_report.py             ← templating + retention + archive index
│   └── routine.py                   ← routine.json + run-stamp + clear-archive
├── docs/local-development.md        ← this file
└── README.md                        ← user-facing install + usage
```

**Plugin paths in SKILL.md** use `${CLAUDE_PLUGIN_ROOT}`. That variable is only set when the skill runs as a plugin (loaded via `--plugin-dir` or `/plugin install`). If you try to run the plugin's `SKILL.md` bash snippets from a regular shell, that variable is empty — use the real path or run the script directly.

**Temp file location** is the platform temp dir (`/var/folders/...` on macOS, `/tmp` on Linux, `%TEMP%` on Windows). Find it with:

```bash
python3 -c 'import tempfile; print(tempfile.gettempdir())'
```

---

## 4. Gotchas

- **No transcripts means an empty report.** If you haven't used Claude Code in the last 30 days, every section will read "0 of 0". That's correct behavior, not a bug.
- **Cowork paths are macOS-only.** On Linux/Windows the scanner silently skips them, and the coverage note should say so. If you're on a non-Mac dev box, don't panic if "Cowork transcripts: 0" is all you see.
- **`Read` on a `SKILL.md` is a heuristic.** The scanner drops bare reads (reads not followed by another tool call in the same turn) as likely false positives. You can see them in the snapshot under `events_audit.bare_read_skill_md` if you're debugging attribution.
- **The Python fallback analysis is on purpose generic.** Running `render_report.py` without an analysis JSON will produce a valid report with stub content — useful for UI iteration, not for production. The whole point of the plugin is that the agent writes the analysis.
- **Editing CSS during a `--plugin-dir` session:** `/reload-plugins` picks up `SKILL.md` changes but the template/CSS files are read at `render_report.py` execution time, so changes take effect on the next audit run with no reload needed.

---

## 5. Before opening a PR

1. Run `/tinyhat:audit` and confirm the report opens without template errors.
2. Run `/tinyhat:open` and confirm no regeneration happens.
3. Run `/tinyhat:history` and confirm the index lists today's snapshot.
4. Confirm the report-header `all reports →` link takes you back to the index, and each index entry re-opens its report.
5. Spot-check at least one session timestamp is your local time (e.g. `2026-04-22 21:04`, not `2026-04-23T02:04`).
6. If you touched attribution in `gather_snapshot.py`, spot-check `snapshot["events_audit"]` for unexpected unknowns.

Then follow [AGENTS.md](../AGENTS.md) for commit + PR conventions.
