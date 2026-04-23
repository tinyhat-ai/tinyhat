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

## Chat summary

After the renderer finishes, you write a short summary in chat. That's
the **terminal-first** default: most users read the summary and stop
there, so it has to earn the room it takes up.

### Shape

Three short paragraphs. No headings, no bullet marathons.

1. **Headline + top skills.** Literal installed/active numbers plus
   the top 2–3 skills from `snapshot.top_skills`, backticked.
2. **One standout.** Pick the single sharpest line from
   `what_stands_out` — the one most likely to make the user lean in.
   Not all of them, just one.
3. **Full-report link.** A clickable `file://` URL to
   `~/.claude/tinyhat/latest/report.html`, absolute path expanded.

### Example

> Scanned 121 installed skills, 14 active in the last 30 days. Top
> skills: `plan-eng-review`, `plan-ceo-review`, `browse`.
>
> What stood out: planning-review skills made up 7 of 17 runs this
> window — review prep is the strongest single pattern.
>
> Full report: `file:///Users/you/.claude/tinyhat/latest/report.html`

### Rules

- **Never re-run `gather_snapshot.py` to write this summary.** Read
  what you already produced — `stats`, `top_skills`, and
  `what_stands_out` are all in the snapshot and analysis JSON you just
  wrote.
- **Expand the `~/` to an absolute path** in the `file://` URL so it's
  clickable in the terminal. `echo $HOME` if you need to.
- **Don't add a fourth paragraph.** No "want me to open it?" follow-up
  — a link is enough. If the user wants to dig in they'll say so.
- **Skip the chat summary only when `--archive` is set without user
  interaction** (the adaptive daily run) — it's background work;
  surfacing it would be noise.

## How the rendering works

`render_report.py` replaces template slots with snapshot facts and your
analysis strings. If a key in your analysis JSON is missing, the
renderer falls back to a Python-derived default. That default is
safe but generic — which is exactly what this skill is trying to avoid.
Fill every field.

The renderer also writes `snapshot.json` and `analysis.json` next to
the HTML in both `latest/` and (when `--archive`) `archive/YYYY-MM-DD/`.
Those two files are the durable view of everything you produced on
this run — a follow-up turn (or `/tinyhat:open`) can answer questions
about this audit by reading them instead of re-scanning.
