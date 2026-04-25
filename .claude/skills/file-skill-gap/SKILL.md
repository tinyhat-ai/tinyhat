---
name: file-skill-gap
description: Use when, while working another ticket on the tinyhat repo, you notice a reusable workflow gap that *would* be a skill — and you're tempted to build it now. This skill captures the gap as a separate follow-up issue with enough evidence for a future implementer, then sends you back to the original task. Development skills live in `.claude/skills/`, never the public `skills/` directory. Invoke whenever you catch yourself thinking "this should be a skill" on unrelated work.
---

# file-skill-gap — capture a skill opportunity, don't detour into building it

You're mid-ticket. Something just made you think *"this should be a
skill."* The instinct is to write it now. **That's almost always the
wrong move on this ticket.** Skill-authoring belongs to its own issue
so review stays focused, scope stays clean, and the original work
ships. This skill files the follow-up and sends you back.

## 1. The no-detour rule

Ask: *does the ticket I'm on explicitly ask for skill work?*

- **No** (the common case) → do not create or sharpen a skill in this
  PR. File a follow-up (rest of this skill) and return.
- **Yes** — title or body names a skill, has the `skill` label, or
  the maintainer asked directly → skill work is in-scope; finish on
  this branch using [`update-guidance`](../update-guidance/SKILL.md).

If unsure, treat it as "no." A follow-up issue is cheap; a sprawling
PR that mixes product and process is not.

## 2. Decide whether the gap qualifies

File only when at least one holds:

- **Repeatable workflow** — the same sequence will run again.
- **Multi-step procedure** — three or more ordered steps, branchy,
  easy to get wrong from memory.
- **High-cost mistake pattern** — getting it wrong burns time, leaks
  secrets, breaks shared state, or touches production.
- **Recurring context** — the same paths/conventions/invariants get
  re-derived every time the topic comes up.
- **Tool / process integration** — wraps an external tool, API, or
  multi-system flow with setup or gotchas.

"I wish this command had a flag" is a code/doc fix, not a skill.

## 3. Search the tracker for duplicates

Skill ideas pile up. Comment new evidence on a duplicate before
opening a new issue.

```bash
gh issue list --repo tinyhat-ai/tinyhat --label skill --state all \
  --search "<two or three keywords>" --json number,title,state,url
```

Also browse [`AGENTS.md`'s skills index](../../../AGENTS.md#skills-index--contribution-operations)
and `ls .claude/skills/` — the skill may already exist and just need
sharpening (still its own issue, not a fix in your current PR).

## 4. File the issue

**Path matters.** Development skills (helping an agent contribute to
*this* repo) live in `.claude/skills/`. User-facing, distributed
skills (shipped via the plugin) live in `skills/`. Name the target in
the issue body so the implementer doesn't pick the wrong one.

**Issue type vs. label.** Use the tracker's native `skill` issue type
when one exists (some Linear/Jira projects, GitHub repos with custom
issue types configured). Otherwise apply a `skill` label or equivalent
metadata field.

For **tinyhat on GitHub right now**: no native `skill` type, so apply
the `skill` label plus `enhancement`.

```bash
gh issue create --repo tinyhat-ai/tinyhat \
  --title "feat(skills): <imperative one-liner>" \
  --label skill --label enhancement \
  --body "$(cat <<'EOF'
[fill the body using the section 5 checklist]
EOF
)"
```

If a tracker exposes a native skill type, set it via the tracker's
API instead of — not in addition to — the label fallback.

## 5. Required evidence checklist

A skill-gap issue is only useful if a future implementer can act on
it without re-reading the transcript. Include all of:

- **Source ticket** — the issue / PR you were on. One link.
- **Concrete friction** — the specific mistake, repeated reasoning,
  or decision point that made you reach for a skill. One paragraph.
- **Reproducible evidence** — file paths, commands run, error
  messages, log excerpts, or short transcript quotes. Trim to
  load-bearing.
- **Why not now** — one sentence on why doing the skill inside the
  source ticket would be scope creep.
- **First-pass trigger / description** — a draft of what the eventual
  `SKILL.md` description would say. Discovery metadata, not finished
  prose.
- **Acceptance criteria** — what "done" looks like for the future
  skill PR (3–6 bullets).
- **Privacy boundary** — anything from the source ticket that must
  **not** be pasted into a public tracker (internal URLs,
  `CLAUDE.local.md` content, customer data, credentials). If you
  can't sanitize, file privately or escalate to the maintainer
  instead of leaking.

## 6. Return to the original task

Drop a one-line note on the source ticket pointing at the new issue:

> Filed `#NNN` for the skill gap noticed while working this; not
> blocking and not in this PR.

Then resume. Resist re-opening the skill question in this PR even if
review touches the same area — that's what the new issue is for.

## 7. Worked example (dry run)

Working `#142` (a feature endpoint), you realize there's no canonical
"spin up the test DB, apply migrations, seed fixtures" recipe. That's
a skill-shaped gap. You file:

```
Title: feat(skills): add a local-test-db setup skill

## Source
Noticed while working #142 (user-export endpoint).

## Friction
No canonical recipe; I read three READMEs and one CI workflow to
piece it together. Easy to skip the seed step and silently get an
empty result set in tests.

## Evidence
- Commands I ended up running: `docker run … postgres:16` →
  `psql -f db/schema.sql` → `python scripts/seed_fixtures.py --env=local`
- Seed script at `scripts/seed_fixtures.py`; not mentioned in
  `README.md` or `CONTRIBUTING.md`.
- CI does the same in `.github/workflows/test.yml:42-78`.

## Why not in #142
Skill-authoring would double the diff and pull review off the
endpoint. Out of scope for the feature ticket.

## First-pass description
"Use to spin up a local Postgres for tinyhat tests, apply
migrations, and load seed fixtures. Invoke before running the
integration test suite locally for the first time."

## Acceptance
- `.claude/skills/local-test-db/SKILL.md` exists, registered in AGENTS.md.
- Steps cover Docker, schema apply, seed load, teardown.
- One worked end-to-end example.
- References the CI workflow as the source of truth for versions.

## Privacy
None — all referenced paths are public.
```

Then on `#142`: *"Filed `#NNN` for the local-test-db skill gap; not
blocking, not in this PR."* Back to the endpoint.

## 8. Non-negotiables

- Never sharpen or create a skill inside an unrelated implementation
  ticket. File a follow-up and return.
- Never paste `CLAUDE.local.md` content, internal URLs, or any
  maintainer-private resource into a public-tracker issue.
- Never file a skill-gap issue without the evidence checklist filled
  in — "we should have a skill for X" gets closed as low-signal.
- Never file in `skills/` (public) when the gap is a contribution /
  development workflow. Those go in `.claude/skills/`.
