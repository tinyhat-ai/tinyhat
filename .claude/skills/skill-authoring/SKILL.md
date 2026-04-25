---
name: skill-authoring
description: Use when creating a new development skill under .claude/skills/ in the tinyhat repo, or sharpening an existing one. Covers the evidence bar for either move, the trigger-first authoring order, frontmatter and progressive-disclosure rules adapted from Anthropic and OpenAI guidance, the quality checklist a skill must pass before merge, and the validation step against realistic scenarios. Sharpening triggers include vague descriptions, agents missing a skill when they should load it, repeated user corrections covered by no current skill, recurring patterns surfaced by /tinyhat:audit, or upstream best-practice changes.
---

# skill-authoring — create or sharpen a development skill

For **development skills** under `.claude/skills/` only — the
contribution-plumbing agents load while working in this repo. Packaged
plugin skills under `skills/` (the `tinyhat:*` commands) have a higher
bar; pause and ask the maintainer. Read
[`update-guidance`](../update-guidance/SKILL.md) first — rules here
are *additive* to its line budgets, anchor hygiene, and
non-duplication policy.

## 1. Decide: new skill or sharpening?

- **New** skill (procedure no current skill covers) → sections 2–6.
- **Sharpening** an existing `SKILL.md` (frontmatter, body, scripts) →
  sections 2–6 plus 7.
- **Rename or split** counts as both — author the new, delete the old,
  migrate references in `AGENTS.md`.

## 2. Evidence gate (required before authoring)

Don't write a skill on speculation. A new or sharpening edit must cite
at least one of:

- A failed or awkward agent session (link the transcript).
- Repeated user corrections no current skill resolves.
- A recurring pattern from `/tinyhat:audit` (mistake clusters or
  skill-creation suggestions).
- A process change in `AGENTS.md` needing procedural detail no
  eagerly-loaded file should carry.
- A better upstream practice from Anthropic or OpenAI guidance (cite).

Record the evidence in the PR body — without it, the PR is sent back.

## 3. Trigger first — write the description before the body

Anthropic's resolver only pre-loads `name` + `description`. The trigger
does the routing; the body never loads if the trigger is vague. Before
opening `SKILL.md`, write three things — if you can't, the skill isn't
ready:

1. **Two or three intents that should load this skill** — sentences a
   user might actually type.
2. **One or two intents that should *not* load it** — what it could be
   confused with (e.g. `dev-reset` vs `tinyhat:audit` both sound like
   "clean up", but only one wipes state).
3. **The negative scope** — what this skill is *not* responsible for,
   so the body can defer rather than re-litigate.

## 4. Frontmatter

| Field | Rule |
|---|---|
| `name` | Kebab-case, ≤64 chars, gerund-ish (`skill-authoring`, not `skill-author-helper`). Avoid `helper`, `utils`, `tools`, `manager`. Match the directory name. |
| `description` | Third person ("Use when…", "Covers…"), ≤1024 chars, names *what* + *when*, embeds the section-3 trigger keywords, and ideally the negative scope. |
| `argument-hint`, `allowed-tools` | Only when the skill wraps a script or has a flag-driven flow (see `dev-reset`). Not speculative. |

## 5. Body — concise, progressive, no duplication

- **≤150 lines** target per `update-guidance`. Overflow goes into a
  sibling reference, **one level deep only** — Claude reads nested
  files shallowly.
- **No duplicated policy.** Cross-agent rules live in `AGENTS.md`;
  link, don't paste.
- **Concrete examples beat descriptions** when output style matters
  (commit subjects, PR titles, frontmatter). Show one.
- **Numbered steps** for sequences; copy-paste checklists when the
  agent will tick items off.
- **Set degrees of freedom deliberately** — judgment work as prose;
  deterministic ops as exact commands with "Do not modify".
- **Scripts only when** the work is deterministic, repeated, or
  fragile enough that prose drifts (see `dev-reset`).

## 6. Validate before opening the PR

Against the scenarios from section 3, and recorded in the PR body:

1. **Trigger dry-run.** Confirm each "should load" intent routes to
   the skill and each "should not load" intent doesn't. Cleanest
   test: a fresh Claude session given just the description.
2. **Procedure dry-run.** Walk the body against one realistic scenario
   end to end. Where does the agent get stuck or improvise? Tighten.
3. **Cross-skill check.** Does another `.claude/skills/<x>/SKILL.md`
   already cover part of this? Link instead of duplicating.

## 7. Sharpening — record the gap

Sharpening reuses sections 2–6 plus three short lines in the PR body
(one gap per PR — don't bundle unrelated sharpenings):

- **Observed gap.** What evidence (section 2) prompted the edit.
- **Revised trigger/procedure.** What changed and why.
- **Validation.** Which scenarios you re-ran and what now happens.

### Before/after example

**Before** — vague, agents kept missing it on PDF tasks:

```yaml
name: file-tools
description: Use when working with files.
```

**Evidence:** five `/tinyhat:audit` sessions where the user asked
"extract the tables from this PDF" and the agent improvised with
`pdftotext` instead of loading this skill.

**After** — specific name, trigger keywords, negative scope:

```yaml
name: extract-pdf-tables
description: Use when extracting tabular data from a PDF — invoices, financial statements, scanned reports. Covers layout detection and the CSV output format. Do NOT use for plain-text extraction (use the model directly) or image-only PDFs (those need OCR first; see ocr-pdf).
```

**Validation:** re-ran the five transcripts; the new description
routed four. The fifth was image-only and correctly fell through to
the negative-scope hint.

## 8. Quality checklist (must pass before merge)

- [ ] Lives in `.claude/skills/<name>/`, not `skills/`.
- [ ] `name` is kebab-case, ≤64 chars, specific (no `helper`/`utils`).
- [ ] `description` is third-person, ≤1024 chars, names trigger intents
      and ideally negative scope.
- [ ] Body ≤150 lines, no overlap with `AGENTS.md`, `CLAUDE.md`, or
      another skill.
- [ ] At least one concrete example where output style matters.
- [ ] Numbered workflow when there is a sequence.
- [ ] Scripts only where the work earns one.
- [ ] PR body records evidence (§2) and validation (§6 — and §7 if
      sharpening).
- [ ] Cross-refs grep'd for broken anchors per `update-guidance`.

## 9. Non-negotiables

- Never put a development skill in `skills/`, or a packaged skill in
  `.claude/skills/`.
- Never author or sharpen a skill without an evidence line in the PR
  body — speculation drifts.
- Never duplicate `AGENTS.md` policy in a skill body. Link instead.

## Sources

Adapted from
[Anthropic's agent-skills best practices](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices)
(trigger-first frontmatter, third-person descriptions, progressive
disclosure, gerund naming, deterministic-work scripts, A-authors-B-uses
validation) and [OpenAI Academy skills](https://academy.openai.com/public/resources/skills)
(small composable skills, explicit inputs/steps/output/checks, no skill
for one-off or highly variable tasks).
