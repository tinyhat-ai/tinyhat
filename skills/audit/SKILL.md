---
description: Audit which Claude Code skills you actually use, which look dormant, and what to create next. Produces an agent-authored local HTML+markdown report on the data already on disk. Triggers on "audit my skills", "run a skill audit", "review my skill usage", "clean up unused skills", "trim my skill set", "which skills should I remove", "how am I using Claude", "which skills am I actually using", "what skills should I create", "refresh my tinyhat report", or explicit /tinyhat:audit invocations.
argument-hint: [--archive] [--open]
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
| _(empty)_ | Run the audit, summarise in chat with a link to the HTML. Do **not** auto-open the browser. |
| `--open` | Also open the HTML in the default browser at the end. |
| `--archive` | Also write today's dated archive snapshot. Implies no auto-open — used by the adaptive daily run. |

## Skill-relative script paths

`${CLAUDE_SKILL_DIR}` is rendered into the skill content before Claude
runs any Bash blocks. It points at this skill's directory, so reach the
bundled scripts with `"${CLAUDE_SKILL_DIR}/../../scripts/..."` instead
of caching shared plugin state under `~/.claude/tinyhat/`.

## Load-time daily check (before handling the user's request)

Every time this skill loads, silently check whether today's adaptive
snapshot should fire. Do not ask the user.

```!
python3 "${CLAUDE_SKILL_DIR}/../../scripts/routine.py" check
```

If exit non-zero, skip — proceed to the user's actual request.
If exit zero, run the full audit flow with `--archive`, then continue
to the user's request. Add one short line so the user knows today's
snapshot refreshed. Never block the user's request on this.

## The audit flow

### 1. Gather the snapshot

```bash
python3 "${CLAUDE_SKILL_DIR}/../../scripts/gather_snapshot.py"
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
# Default — writes latest/ and archive index; no browser:
python3 "${CLAUDE_SKILL_DIR}/../../scripts/render_report.py"

# User passed --open — also open the HTML at the end:
python3 "${CLAUDE_SKILL_DIR}/../../scripts/render_report.py" --open

# User passed --archive (or the adaptive daily fired) — write the
# dated archive copy too; do NOT open the browser:
python3 "${CLAUDE_SKILL_DIR}/../../scripts/render_report.py" --archive
```

Rendering always writes four files into `~/.claude/tinyhat/latest/`:

- `report.html` · `report.md` — the view.
- `snapshot.json` · `analysis.json` — the data you (or a follow-up
  turn) can read without re-running `gather_snapshot.py`.

The renderer also rewrites `~/.claude/tinyhat/archive/index.html` so
the history page always reflects the latest run. When `--archive` is
passed, the same four files land in `archive/YYYY-MM-DD/`.

### 4. Summarise in chat (always)

Write 2–3 sentences in chat, built directly from the analysis you just
wrote. The default experience is **terminal-first** — most users won't
open the HTML unless something in the summary pulls them in.

Lead with the literal headline number, name the top 2–3 skills from
`snapshot.top_skills`, and surface one observation from
`what_stands_out`. End with a clickable file-URL to the full report:

> Scanned `<INSTALLED_COUNT>` installed skills, `<ACTIVE_COUNT>` active
> in the last `<WINDOW_DAYS>` days. Top skills: `<skill-a>`, `<skill-b>`,
> `<skill-c>`.
>
> What stood out: `<one line from what_stands_out>`.
>
> Full report: `file:///Users/<you>/.claude/tinyhat/latest/report.html`

See [`references/writing-the-analysis.md`](references/writing-the-analysis.md#chat-summary)
for the exact shape and examples.

### 5. Open the HTML (only if `--open` was passed)

Default is **no auto-open**. The chat summary above already surfaces
the headline; users who want the HTML click the link in the summary.

When the user passed `--open`, and only then:

```bash
open ~/.claude/tinyhat/latest/report.html        # macOS
xdg-open ~/.claude/tinyhat/latest/report.html    # Linux
start ~/.claude/tinyhat/latest/report.html       # Windows
```

## Paths

- Scripts: bundled under `<plugin>/scripts/`, invoked here via `${CLAUDE_SKILL_DIR}/../../scripts/...`
- Transient: `<tempdir>/tinyhat-snapshot.json`, `<tempdir>/tinyhat-analysis.json`
- Latest: `~/.claude/tinyhat/latest/report.{md,html}` + `snapshot.json` + `analysis.json` + `run-stamp.txt`
- Archive: `~/.claude/tinyhat/archive/YYYY-MM-DD/report.{md,html}` + `snapshot.json` + `analysis.json` + `index.html`
- Routine state: `~/.claude/tinyhat/routine.json`

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
