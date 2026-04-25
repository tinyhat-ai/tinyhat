---
name: audit
description: Audit which Claude Code skills you actually use, which look dormant, and what to create next. Produces an agent-authored local HTML+markdown report on the data already on disk. Triggers on "audit my skills", "run a skill audit", "review my skill usage", "clean up unused skills", "trim my skill set", "which skills should I remove", "how am I using Claude", "which skills am I actually using", "what skills should I create", "refresh my tinyhat report", or explicit /tinyhat:audit invocations.
argument-hint: [--archive] [--open]
allowed-tools: Bash(python3 *) Bash(CLAUDE_PLUGIN_DATA=* python3 *) Bash(open *) Bash(xdg-open *) Bash(start *) Read Write
---

# tinyhat:audit — local skill-usage audit, agent-authored

Tinyhat is local and read-only. A Python helper scans the Claude data
already on disk and emits a structured JSON snapshot. **You (the agent)
read that snapshot and write the editorial layer** — headline, what
stands out, recommendations. A second Python helper merges snapshot +
analysis into one markdown report and one HTML snapshot.

**Why the agent writes the analysis:** a Python script would always
say the same thing. The value of running this inside Claude Code is
that the agent looks at *this* user's *this* week and picks out what's
actually worth mentioning.

## Related skills

- `/tinyhat:open` — open the most recent report without regenerating.
- `/tinyhat:history` — open the archive index (latest + all dated snapshots).
- `/tinyhat:routine` — manage the adaptive daily refresh + diagnostic helpers (status/on/off/where/clear).

## Flags

| `$ARGUMENTS` | What happens |
|---|---|
| _(empty)_ | Run the audit, write the report, and give the user the terminal briefing with a numbered next-action menu. Do **not** auto-open the browser. |
| `--open` | Also open the HTML in the default browser at the end, in addition to the terminal briefing. |
| `--archive` | Also write today's dated archive snapshot. Implies no auto-open — used by the adaptive daily run. |

## Skill-relative script paths

`${CLAUDE_SKILL_DIR}` is rendered into the skill content before Claude
runs any Bash blocks. It points at this skill's directory, so reach the
bundled scripts with `"${CLAUDE_SKILL_DIR}/../../scripts/..."` instead
of caching shared plugin state under a raw home-directory path. Use
`${CLAUDE_PLUGIN_DATA}` for any persisted Tinyhat output path you need
to mention to the user.

## Load-time daily check (before handling the user's request)

Every time this skill loads, silently check whether today's adaptive
snapshot should fire. Do not ask the user.

```!
python3 "${CLAUDE_SKILL_DIR}/../../scripts/routine.py" check
```

If the output starts with `skip:`, do nothing adaptive and proceed to
the user's actual request. Do not mention the skipped adaptive run.
If the output starts with `fire:`, run the full audit flow with
`--archive`, then continue to the user's request. Add one short line
so the user knows today's snapshot refreshed. Never block the user's
request on this.

### Heads-up before regenerating a same-day report

If the `skip:` line is specifically `skip: already ran today
(YYYY-MM-DD)` **and** the user explicitly asked for an audit (slash
command or a natural-language audit prompt), print one short line
before running the audit flow:

> Note: today's report (`YYYY-MM-DD`) already exists. Regenerating with a fresh analysis — this replaces the earlier snapshot.

Use the date from the parenthesized `(YYYY-MM-DD)` in the `check`
output. Skip the heads-up on the other `skip:` reasons (e.g.
`routine disabled`) — those don't imply a same-day report exists.

## The audit flow

### 1. Gather the snapshot

```bash
python3 "${CLAUDE_SKILL_DIR}/../../scripts/gather_snapshot.py"
```

Writes two files side by side:

- `<temp>/tinyhat-snapshot.json` — **compact**, aggregate-only. This
  is what you `Read` in step 2; it fits in a single Read call even on
  100+ skill installations.
- `<temp>/tinyhat-snapshot-detail.json` — **detail**, the full
  snapshot with per-session rows, full inventory, and raw events. The
  renderer consumes this; you only need to touch it if an observation
  requires drilling into a specific session or event.

Both paths are printed to stderr.

### 2. Read the snapshot and write your analysis

Read the **compact** snapshot (`<temp>/tinyhat-snapshot.json`). It has
every aggregate field the analysis cites. If you need a specific
session row or inventory entry, read the detail file — but prefer the
compact file so you don't burn tokens on data you won't cite.

Then write `<temp>/tinyhat-analysis.json` via the Bash heredoc below —
**do not use the `Write` tool**, it requires a prior `Read` on the
path and will fail for a brand-new temp file. Detailed field-by-field
guidance is in
[`references/writing-the-analysis.md`](references/writing-the-analysis.md) —
read it the first time you run this skill.

```bash
python3 <<'PY'
import json, tempfile, pathlib
out = pathlib.Path(tempfile.gettempdir()) / "tinyhat-analysis.json"
out.write_text(json.dumps({
    "headline": "You have N skills installed. You used M of them in the last 30 days.",
    "headline_sub": "One short supporting sentence.",
    "what_stands_out": ["3–5 specific observations citing real names, counts, dates"],
    "dormant_commentary": "One or two sentences about the dormant surface.",
    "skill_recommendations": [
        {"name": "...", "confidence": "high", "headline": "...", "why": "...", "triggers": ["..."]}
    ],
    "next_actions": [
        {"verb": "draft-skill", "label": "Draft `implement-feature`", "context": "...", "impact": "high"}
    ],
    "coverage_note": "One paragraph; honest about what was scanned and what's uncertain.",
}, indent=2))
print(f"Wrote {out}")
PY
```

Fill the dict with your real analysis before running. Python resolves
the correct temp directory on every OS and surfaces any JSON-shaped
mistakes as a clean error.

**Non-negotiables:**
- Use literal numbers from `snapshot.stats` for the headline.
- Only reference skills that appear in the compact snapshot's
  `top_skills` or `dormant_by_origin` (together these cover every
  installed skill). Check there before naming a skill in a
  recommendation so you don't suggest one the user already has.
- Recommendations must be grounded in tool/session patterns you can
  cite from `tool_totals`, `aggregate_tools`, or
  `session_tool_patterns`. No speculation.

### 3. Render

```bash
# Default — writes latest/ and archive index; no browser:
python3 "${CLAUDE_SKILL_DIR}/../../scripts/render_report.py"

# User passed --archive (or the adaptive daily fired) — write the
# dated archive copy too; do NOT open the browser:
python3 "${CLAUDE_SKILL_DIR}/../../scripts/render_report.py" --archive
```

Rendering always writes four files into `${CLAUDE_PLUGIN_DATA}/latest/`:

- `report.html` · `report.md` — the view.
- `snapshot.json` · `analysis.json` — the data you (or a follow-up
  turn) can read without re-running `gather_snapshot.py`.

The renderer also rewrites `${CLAUDE_PLUGIN_DATA}/archive/index.html` so
the history page always reflects the latest run. When `--archive` is
passed, the same four files land in `archive/YYYY-MM-DD/`.

### 4. Give the terminal briefing (always)

Keep it compact and terminal-safe:

1. Start with a fenced `text` block containing the two-line percentage
   strip. Use ASCII only: `#`, `-`, brackets, and plain digits. Do not
   use ANSI color codes, Unicode block characters, tables, or doughnut
   metaphors in the chat reply.
2. Follow with one short sentence that names the headline and one
   specific observation from `what_stands_out`.
3. Then show a numbered list of 3–5 concrete next steps from
   `next_actions`.
   - Exactly one item should be the defer option.
   - Exactly one item should be the full-report escape hatch.
   - Order by impact, not by category.
4. If the user replies with the number for the full-report action, or
   asks to see the HTML, open `${CLAUDE_PLUGIN_DATA}/latest/report.html`.
5. Prefer a plain numbered list over `AskUserQuestion` for now. The
   list must work cleanly in CLI scrollback, the desktop Code tab, and
   Cowork.

See [`references/writing-the-analysis.md`](references/writing-the-analysis.md#chat-briefing)
for the exact shape, examples, and the required `next_actions` classes.

### 5. Open the HTML (only if `--open` was passed)

Default is **no auto-open**. The terminal briefing above already
surfaces the headline plus a next-action menu; users who want the HTML
pick the open-report option from that menu.

When the user passed `--open`, and only then:

```bash
open "${CLAUDE_PLUGIN_DATA}/latest/report.html"        # macOS
xdg-open "${CLAUDE_PLUGIN_DATA}/latest/report.html"    # Linux
start "${CLAUDE_PLUGIN_DATA}/latest/report.html"       # Windows
```

## Paths

- Scripts: bundled under `<plugin>/scripts/`, invoked here via `${CLAUDE_SKILL_DIR}/../../scripts/...`
- Transient: `<tempdir>/tinyhat-snapshot.json` (compact, agent-facing), `<tempdir>/tinyhat-snapshot-detail.json` (detail, renderer-facing), `<tempdir>/tinyhat-analysis.json`
- Latest: `${CLAUDE_PLUGIN_DATA}/latest/report.{md,html}` + `snapshot.json` + `analysis.json` + `run-stamp.txt`
- Archive: `${CLAUDE_PLUGIN_DATA}/archive/YYYY-MM-DD/report.{md,html}` + `snapshot.json` + `analysis.json` + `index.html`
- Routine state: `${CLAUDE_PLUGIN_DATA}/routine.json`

## Gotchas

- **Never fall back to the Python default analysis.** The renderer has
  stubs that work without `analysis.json`, but they read as generic.
  The reason to run this inside Claude Code is the analysis **you**
  write in step 2.
- **Skill inventory varies by OS.** Cowork paths (`~/Library/…`) don't
  exist on Linux or Windows. The scanner skips missing paths silently;
  mention in the coverage note if an expected surface is absent.
- **`Read` on a `SKILL.md`** is a heuristic signal. The scanner drops
  bare reads as likely false positives — trust the snapshot's counts.
- **Load-time daily check must be silent on skip.**
