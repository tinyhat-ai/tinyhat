# Writing the analysis JSON — field-by-field

Detailed guidance for step 2 of the `tinyhat:skill-audit` flow. Read this
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

## How the rendering works

`render_report.py` replaces template slots with snapshot facts and your
analysis strings. If a key in your analysis JSON is missing, the
renderer falls back to a Python-derived default. That default is
safe but generic — which is exactly what this skill is trying to avoid.
Fill every field.
