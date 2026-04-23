# Writing the analysis JSON — field-by-field

Detailed guidance for step 2 of the `tinyhat:audit` flow. Read this
the first time you run the skill in a session. The main `SKILL.md`
summarises the contract; this file tells you how to write good content
inside it.

## The snapshot you're reading

`gather_snapshot.py` emits a JSON file with these top-level keys:

| Key | What's in it |
|---|---|
| `meta` | `generated_at`, `window_days`, `window_start`, `window_end` |
| `stats` | `installed_count`, `active_count`, `skill_runs_total`, `sessions_total`, `sessions_with_skills`, `turns_total`, `tokens_total`, `tokens_total_compact` |
| `inventory` | `{skill-name: {path, origin, raw_scope, pack, summary, product}}` |
| `top_skills` | ranked list — `{skill, runs, last_used, summary, origin, pack, raw_scope}` |
| `skill_counts` | `{skill-name: run-count}` over the window |
| `last_seen` | `{skill-name: ISO timestamp}` |
| `sessions` | per-session rows — `session_id, title, surface, project, last_used, turns, tokens_total, tool_uses, total_tool_uses, skill_runs, skill_counter, model, transcript` |
| `events` | attributed skill events (deduplicated, in window) |
| `events_audit` | `bare_read_skill_md` (dropped), `unknown_names`, `unknown_event_count` |
| `tool_totals` | total calls per tool across the window |
| `aggregate_tools` | `[{tool, calls, sessions}]` ranked by calls |
| `daily_rollups` | per-day `{date, sessions, skill_sessions, turns, tokens, skill_runs}` |
| `dormant_by_origin` | `{origin: [skill-names]}` |
| `installed_by_origin` | `{origin: count}` |
| `surface_rollups` | `{surface: session-count}` |
| `coverage` | scanner counts — what was read vs. dropped |

Use this as a reference when drafting your observations.

## Field-by-field rules

### `headline`

Literal: *"You have N skills installed. You used M of them in the last
K days."* — N, M, K from `stats.installed_count`, `stats.active_count`,
`meta.window_days`. Never round. Never embellish. The headline has to
be accurate or the whole report is dismissed.

### `headline_sub`

One short supporting line. Could be "Only 8% of your installed surface
is earning its keep." or "Skill usage is concentrated in the planning
cluster." Never more than one sentence.

### `what_stands_out` (3–5 bullets)

This is where the agent earns its keep. Each bullet should:

- **Cite a specific number** from the snapshot.
- **Reference a specific skill name** where possible.
- **Say *why* it's worth noticing**, not just state the number.
- Be one line. Two max.

Examples of good bullets:

- "Planning-review skills (plan-eng-review, plan-ceo-review,
  plan-design-review) made up 7 of 17 runs — review prep is the
  strongest single pattern this window."
- "`browse` fired 3 times on 2026-04-21 — the browser-verification
  loop is becoming habitual."
- "Only 6 of 39 sessions fired any skill — most Claude time is still
  free-form tool use."

Examples of bad bullets:

- "Skills are useful and you should consider using them more." (vague,
  no citation)
- "You used the planning skills a lot." (no numbers)
- "It looks like you might be interested in cleaning up." (wishy-washy)

Call out **change** when you can see it (e.g. a skill that first
appeared this week, or a skill that stopped firing). The snapshot
doesn't compare across runs in v0, but you can still call a skill
"recent" vs. one last used weeks ago.

### `dormant_commentary`

One or two sentences about the dormant surface. Look at
`dormant_by_origin` — if 70 of 103 dormants are "Project-local",
that's relevant context (they live in repos the user may not be
currently working in, not necessarily dead skills).

### `skill_recommendations` (0–3 items)

Each recommendation:

- `name`: kebab-case, novel (don't propose an already-installed skill).
- `confidence`: `high`, `medium`, or `low`. Be honest.
- `headline`: one-line value prop.
- `why`: 2–3 sentences, grounded in evidence you can point to in
  `snapshot.sessions` or `snapshot.tool_totals`. Cite counts.
- `triggers`: 3–5 natural-language phrases that should activate the
  skill.

**How to find real recommendations:**

1. Look at `tool_totals` — which tools dominate? High `Edit + Bash`
   together suggests an `implement-feature` pattern. High `Read + Grep`
   suggests `explore-codebase`. High `WebSearch + WebFetch` alongside
   `Write` suggests `research-and-write-brief`.
2. Count sessions that match the pattern (`snapshot.sessions`). A
   pattern across 2+ sessions is worth considering; 5+ is high-confidence.
3. Check `snapshot.inventory` — if a similar skill already exists, note
   that and pivot (e.g. "you have `plan-eng-review`; add `plan-sprint`
   for the weekly cadence").

If you can't ground a recommendation in evidence, **omit it**. A
confident two-item list beats a speculative three-item list.

### `next_actions` (3–5 items)

These drive the terminal briefing, the top of `report.md`, and the
simple-mode action list in `report.html`.

Each action has:

- `verb`: stable machine-ish label such as `draft-skill`, `cleanup`,
  `routine`, `open-report`, or `defer`.
- `label`: the imperative action the user sees.
- `context`: one short evidence-backed sentence. Keep it to one line if
  possible.
- `impact`: `high`, `medium`, `low`, or `null`.

Rules of thumb:

- Include **exactly one** `open-report` item.
- Include **exactly one** `defer` item.
- Order by impact, not by category.
- Prefer concrete verbs over topic buckets.
- If the strongest recommendation is a new skill, that usually belongs
  first.
- If plugin-bundled skills dominate the dormant surface, a cleanup
  action belongs near the top.
- Ground the routine action in the current state on disk (on/off, last
  run), not in assumptions.

Example:

- `Draft \`implement-feature\`` — 5 recent sessions leaned hard on Edit
  + Bash, so the build-fix-verify loop is worth capturing.
- `Review the 22 dormant plugin skills` — they are the cleanest cleanup
  targets in this snapshot.
- `Check the daily routine` — currently on; last run 2026-04-23.
- `Open the full HTML report` — charts and session drill-downs live in
  the sibling `report.html`.
- `Do nothing — check back tomorrow` — useful if the user only wanted
  the briefing.

### `coverage_note`

One paragraph. Mention:

- How many transcripts were scanned (`coverage.cli_transcripts`,
  `coverage.cowork_transcripts`).
- Whether GStack telemetry was present (`coverage.gstack_telemetry_present`).
- How many events were dropped (`coverage.unknown_event_count`,
  `coverage.bare_read_skill_md_count`).
- One sentence of honest caveat: counts are directional for ties.

If the user is on Linux or Windows and Cowork paths don't exist, say
so explicitly: *"No Cowork transcripts found — that surface is
macOS-only."*

## Failure modes to avoid

- **Generic analysis.** If your bullets would work for any user, they
  don't belong.
- **Fabricated counts.** If you can't find the number in the snapshot,
  don't cite it.
- **Recommending something the user already has.** Check `inventory`
  first.
- **Burying the lead.** The two pie charts and hero stats are already
  visible; your `what_stands_out` should add signal the charts can't.

## Chat briefing

After the renderer finishes, you write a compact terminal briefing.
That's the **terminal-first** default: most users read the briefing
and stop there, so it has to earn the room it takes up.

### Shape

1. **Percentage strip** — fenced `text` block, ASCII only, two lines:
   - `Skill utilization:    [=========---------]  12%   14 / 121`
   - `Sessions with skills: [==================-]  26%   14 / 54`
   Use `=` and `-` for bars (roughly 20 characters wide). No ANSI
   colors, no Unicode blocks, no tables, no doughnuts.
2. **One-sentence headline + standout.** Name the headline from
   `analysis.headline` and pull one line from `what_stands_out`.
3. **Numbered next-action menu** — 3–5 items straight from
   `next_actions`. Prefix each with a number so the user can reply
   with that number. Include the action's `context` as the trailing
   explanation.

### Example

> ```text
> Skill utilization:    [==----------------]  12%   14 / 121
> Sessions with skills: [=====-------------]  26%   14 / 54
> ```
>
> 121 installed, 14 active this window. What stood out: planning-review
> skills (plan-eng-review, plan-ceo-review, plan-design-review) made
> up 7 of 17 runs — review prep is the strongest single pattern.
>
> Pick a next step:
>   1. Draft `implement-feature` — 4,443 combined Edit+Bash calls across 54 sessions would have benefited.
>   2. Review the 29 dormant plugin-bundled skills — cleanest cleanup targets in this snapshot.
>   3. Check the daily routine — currently on; last run 2026-04-23.
>   4. Open the full HTML report for charts and session drill-downs.
>   5. Do nothing — check back tomorrow.
>
> Reply with a number or the natural-language form.

### Rules

- **Never re-run `gather_snapshot.py` to write this briefing.** Read
  what you already produced — `stats`, `top_skills`, `what_stands_out`,
  and `next_actions` are all in the snapshot and analysis JSON.
- **Use literal numbers from `snapshot.stats`.** Don't paraphrase
  counts.
- **Skip the briefing only when `--archive` fires non-interactively**
  (the adaptive daily run) — it's background work; surfacing it would
  be noise.
- **When the user replies with a number**, map it back to the
  corresponding `next_actions[i].verb` and act:
  - `open-report` → open `${CLAUDE_PLUGIN_DATA}/latest/report.html`.
  - `draft-skill` → hand off to the skill-drafting flow.
  - `cleanup` → list the dormant skills and help the user pick.
  - `routine` → invoke `/tinyhat:routine` sub-commands.
  - `defer` → say "ok" and stop.

## How the rendering works

`render_report.py` replaces template slots with snapshot facts and your
analysis strings. If a key in your analysis JSON is missing, the
renderer falls back to a Python-derived default. That default is
safe but generic — which is exactly what this skill is trying to avoid.
Fill every field.

The terminal briefing at the end of the skill mirrors the same
`next_actions` and the same two-percentage strip as the top of
`report.md`, but the chat-side strip is rendered by the skill (from
`snapshot.stats`), not by `analysis.json`.

The renderer also writes `snapshot.json` and `analysis.json` next to
the HTML in both `latest/` and (when `--archive`) `archive/YYYY-MM-DD/`.
Those two files are the durable view of everything you produced on
this run — a follow-up turn (or `/tinyhat:open`) can answer questions
about this audit by reading them instead of re-scanning.
