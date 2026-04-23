---
description: Audit which Claude Code skills you actually use, which look dormant, and what to create next. Produces an agent-authored local HTML+markdown report on the data already on disk. Triggers on "audit my skills", "run a skill audit", "review my skill usage", "clean up unused skills", "trim my skill set", "which skills should I remove", "how am I using Claude", "which skills am I actually using", "what skills should I create", "refresh my tinyhat report", or explicit /tinyhat:audit invocations.
argument-hint: [--archive] [--no-open]
allowed-tools: Bash(python3 *) Bash(open *) Bash(xdg-open *) Bash(start *) Read Write
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
| _(empty)_ | Run the audit, open the HTML. |
| `--archive` | Also write today's dated archive snapshot. |
| `--no-open` | Skip the browser. Used by the adaptive daily run. |

## Load-time: persist the plugin root

`${CLAUDE_PLUGIN_ROOT}` only expands inside `!`-prefixed blocks.
Non-`!` Bash blocks (the ones you run via the `Bash` tool later) see it
empty. Persist it to a known file at load time so those calls can find
the scripts no matter which version the user has installed.

```!
mkdir -p ~/.claude/tinyhat && printf '%s' "${CLAUDE_PLUGIN_ROOT}" > ~/.claude/tinyhat/.plugin-root
```

All non-`!` Bash blocks below resolve the scripts dir with
`"$(cat ~/.claude/tinyhat/.plugin-root)/scripts/..."`. Don't hardcode
the plugin path — it changes per user and per version.

## Load-time daily check (before handling the user's request)

Every time this skill loads, silently check whether today's adaptive
snapshot should fire. Do not ask the user.

```!
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/routine.py" check
```

If exit non-zero, skip — proceed to the user's actual request.
If exit zero, run the full audit flow with `--archive --no-open`, then
continue to the user's request. Add one short line so the user knows
today's snapshot refreshed. Never block the user's request on this.

## The audit flow

### 1. Gather the snapshot

```bash
python3 "$(cat ~/.claude/tinyhat/.plugin-root)/scripts/gather_snapshot.py"
```

Writes `<temp>/tinyhat-snapshot.json`. The path is printed to stderr.

### 2. Read the snapshot and write your analysis

Read the snapshot. Then write `<temp>/tinyhat-analysis.json` with
these keys. Detailed field-by-field guidance is in
[`references/writing-the-analysis.md`](references/writing-the-analysis.md) —
read it the first time you run this skill.

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
# Manual, opens in browser:
python3 "$(cat ~/.claude/tinyhat/.plugin-root)/scripts/render_report.py" --open

# Adaptive daily or explicit --archive:
python3 "$(cat ~/.claude/tinyhat/.plugin-root)/scripts/render_report.py" --archive
```

The renderer also rewrites `~/.claude/tinyhat/archive/index.html` so
the history page always reflects the latest run.

### 4. Open the HTML (if you didn't use `--open`)

```bash
open ~/.claude/tinyhat/latest/report.html        # macOS
xdg-open ~/.claude/tinyhat/latest/report.html    # Linux
start ~/.claude/tinyhat/latest/report.html       # Windows
```

### 5. Tell the user

One or two sentences max. Reference one specific observation from
`what_stands_out`. Point them at the report.

## Paths

- Scripts: `${CLAUDE_PLUGIN_ROOT}/scripts/` — resolved at runtime via `~/.claude/tinyhat/.plugin-root` (written in the load-time `!` block)
- Transient: `<tempdir>/tinyhat-snapshot.json`, `<tempdir>/tinyhat-analysis.json`
- Latest: `~/.claude/tinyhat/latest/report.{md,html}` + `run-stamp.txt`
- Archive: `~/.claude/tinyhat/archive/YYYY-MM-DD/report.{md,html}` + `index.html`
- Routine state: `~/.claude/tinyhat/routine.json`, `~/.claude/tinyhat/.plugin-root`

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
