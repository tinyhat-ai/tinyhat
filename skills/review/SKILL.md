---
description: Produce an agent-authored skill-usage report for Claude Code — which skills are actually used, which look dormant, what to create next. Triggers on "how am I using Claude", "which skills am I actually using", "review my skill usage", "open my tinyhat report", "clean up unused skills", "what skills should I create", or explicit /tinyhat:review invocations. Can take sub-commands as arguments (routine on/off/status, where, clear-archive, --archive, --no-open).
argument-hint: [--archive] [--no-open] | routine on|off|status | where | clear-archive
allowed-tools: Bash(python3 *) Bash(open *) Bash(xdg-open *) Bash(start *) Read Write
---

# tinyhat:review — local skill-usage report, agent-authored

Tinyhat is local and read-only. A Python helper scans the Claude data
already on disk and emits a structured JSON snapshot. You (the agent)
read that snapshot and write the editorial layer — headline, what stands
out, recommendations. A second Python helper merges snapshot + analysis
into one markdown report and one HTML snapshot.

**Why the agent writes the analysis:** a Python script would always say
the same thing. The value of running this inside Claude Code is that
the agent looks at *this* user's *this* week and picks out what's
actually worth mentioning.

## Sub-commands (dispatch on `$ARGUMENTS`)

| `$ARGUMENTS` matches | What to do |
|---|---|
| (empty) or starts with `--archive` / `--no-open` | Run the full review flow below. Pass flags straight to `render_report.py`. |
| starts with `routine` | Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/routine.py" <rest>`. Print the output verbatim. |
| `where` | Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/routine.py" where`. |
| `clear-archive` | Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/routine.py" clear-archive`. |

## Load-time daily check (before handling the user's request)

Every time this skill loads, silently check whether today's adaptive
snapshot should fire. Do not ask the user.

```!
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/routine.py" check
```

If that exits **non-zero**, skip — proceed to the user's actual request.

If it exits **zero**, run the full review flow below with `--archive
--no-open`, then continue to the user's request. Add one short line to
your reply so the user knows today's snapshot refreshed and where to
find it. Never block the user's request on this.

## The review flow

### 1. Gather the snapshot

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/gather_snapshot.py"
```

By default this writes `<temp>/tinyhat-snapshot.json` where `<temp>` is
the platform temp dir. The script prints the exact path it wrote to
stderr.

### 2. Read the snapshot and write your analysis

Read the snapshot. Then write `<temp>/tinyhat-analysis.json` with these
keys. Detailed field-by-field guidance is in
[`references/writing-the-analysis.md`](references/writing-the-analysis.md) —
read that the first time you run this skill.

```json
{
  "headline": "You have N skills installed. You used M of them in the last 30 days.",
  "headline_sub": "One short supporting sentence.",
  "what_stands_out": ["3–5 specific observations citing real names, counts, dates"],
  "dormant_commentary": "One or two sentences about the dormant surface.",
  "skill_recommendations": [
    {"name": "...", "confidence": "high|medium|low", "headline": "...", "why": "...", "triggers": ["..."]}
  ],
  "coverage_note": "One paragraph; honest about what was scanned and what's uncertain."
}
```

**Non-negotiables:**
- Use literal numbers from `snapshot.stats` for the headline.
- Only reference skills that appear in `snapshot.inventory`.
- Recommendations must be grounded in tool/session patterns you can
  cite from the snapshot. No speculation.

### 3. Render

```bash
# Manual:
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render_report.py"

# Adaptive daily or explicit --archive:
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render_report.py" --archive
```

The renderer finds the snapshot and analysis in the temp dir, writes
`~/.claude/tinyhat/latest/report.{md,html}`, and (with `--archive`)
mirrors into `archive/YYYY-MM-DD/`. Retention pruning to 31 dated dirs
happens inside the renderer — you don't manage it.

### 4. Open the HTML (unless `--no-open` was passed)

Use the user's default browser. On macOS:

```bash
open ~/.claude/tinyhat/latest/report.html
```

On Linux use `xdg-open`; on Windows `start`. If you don't know the OS,
call the renderer with `--open` and let it use Python's `webbrowser`
module:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render_report.py" --open
```

### 5. Tell the user

One or two sentences max. Reference one specific observation you wrote
in `what_stands_out` and point them to the report. Do not re-paste the
full analysis.

## Paths

- Scripts: `${CLAUDE_PLUGIN_ROOT}/scripts/` (`gather_snapshot.py`, `render_report.py`, `routine.py`)
- Transient: `<tempdir>/tinyhat-snapshot.json`, `<tempdir>/tinyhat-analysis.json`
- Latest: `~/.claude/tinyhat/latest/report.{md,html}` + `run-stamp.txt`
- Archive: `~/.claude/tinyhat/archive/YYYY-MM-DD/`
- Routine state: `~/.claude/tinyhat/routine.json`
- Feedback: `~/.claude/tinyhat/feedback.jsonl`

## Gotchas

- **Never fall back to the Python-only path unless the user explicitly
  wants the raw script.** The renderer has stub defaults that work
  without an analysis JSON, but they read as generic. The reason to run
  this inside Claude Code is the analysis you write in step 2.
- **Skill inventory varies by OS.** Cowork paths (`~/Library/…`) don't
  exist on Linux or Windows. The scanner skips missing paths silently,
  but mention in the coverage note if an expected surface is absent.
- **`Read` on a `SKILL.md`** is a heuristic signal. The scanner drops
  bare reads (those not followed by another tool call) as likely false
  positives. Trust the snapshot's counts.
- **Load-time daily check must be silent on skip.** Only mention the
  daily run if it actually fires.
- **Feedback is local.** If the user reports a mis-ranking in chat,
  append a single JSON line to `~/.claude/tinyhat/feedback.jsonl` —
  never POST it anywhere.
