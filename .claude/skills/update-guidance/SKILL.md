---
name: update-guidance
description: Use when editing any contribution-guidance file in the tinyhat repo — AGENTS.md, CLAUDE.md, CLAUDE.local.md(.example), or a SKILL.md under .claude/skills/ or skills/. Covers where each piece of content belongs, anchor-link hygiene, the line-count budget per file, and the thin-harness-fat-skills rule that keeps eagerly-loaded files small. For SKILL.md edits specifically, defers to the skill-authoring guide.
---

# update-guidance — edit policy files without breaking the pattern

Tinyhat's contribution docs follow the **thin harness, fat skills**
model: files loaded into every agent turn stay small; deep procedural
content lives in skills that load on demand. Before editing, figure out
where the change actually belongs.

**If you're editing a `SKILL.md`** (under `skills/` or
`.claude/skills/`) — stop reading this skill and switch to the
canonical authoring guide:
[`docs/skill-authoring.md`](../../../docs/skill-authoring.md).
Its [§17 Checklist](../../../docs/skill-authoring.md#17-checklist) is
the source of truth for what every SKILL.md edit must clear before
merge.
The rest of this skill covers the *other* guidance files — `AGENTS.md`,
`CLAUDE.md`, `CLAUDE.local.md*` — and the cross-cutting
"where-does-this-content-live" question that applies to all of them.

## 1. Where does this change belong?

| What you're adding | Goes in | Why |
|---|---|---|
| Cross-agent policy (identity, commits, branches, PRs, versioning) | `AGENTS.md` | Canonical source of truth for every agent. |
| A step-by-step procedure for an operation | `.claude/skills/<op>/SKILL.md` | Fat skill; frontmatter loads eagerly, body on demand. |
| Claude-Code-specific tone, framing, scope guards | `CLAUDE.md` | Loaded per-turn by Claude Code. Keep tight. |
| Maintainer-private context | `CLAUDE.local.md` (gitignored) | Must not ship in the public repo. |
| Public-safe example of a local override | `CLAUDE.local.md.example` | Committed; no private URLs, no internal names. |

**Test:** if the content is *procedure* (a sequence of steps, a
checklist, an error-handling recipe), it's almost always a skill. If
it's a *non-negotiable rule* every agent must hold eagerly, it's a
short line in `AGENTS.md`. If it's *framing* ("this is what we're
building, this is out of scope"), it's `CLAUDE.md`.

## 2. Line-count budget

Files loaded every turn cost tokens on every turn. Target ceilings:

| File | Ceiling | Rationale |
|---|---|---|
| `CLAUDE.md` | 50 lines | Loaded every Claude Code turn. |
| `CLAUDE.local.md` | 30 lines | Loaded every Claude Code turn when present. |
| `AGENTS.md` | 120 lines | Read by agents on request; still kept lean. |
| Individual `SKILL.md` | 150 lines | Loaded only when invoked; can be richer. |

Current counts are visible from `wc -l`. If an edit pushes a file over
its ceiling, split the excess into a skill and link from the original.

## 3. Anchor hygiene

Cross-file links use markdown anchors (e.g.
`AGENTS.md#non-negotiables`). When you rename or remove a section:

```bash
grep -rn "AGENTS\.md#" CLAUDE.md CLAUDE.local.md* .github/ .claude/skills/
```

Fix every hit before merging. Broken anchors are silent on GitHub but
mislead an agent reading them.

## 4. Non-duplication

Cross-agent policy lives in `AGENTS.md` only. Agent-specific files link
to sections in `AGENTS.md`; they do **not** copy the text. Skills link
back to `AGENTS.md` for the "why" and contain the "how." Duplicated
policy drifts — always prefer a link over a paste.

## 5. Public vs internal

Every committed guidance file (`AGENTS.md`, `CLAUDE.md`, `SKILL.md`,
`CLAUDE.local.md.example`, PR template) ships in the
open-source release. Before committing, ask: *could a reader of the
public repo learn something I only know from `CLAUDE.local.md` or
other internal material?* If yes, rewrite or move it to
`CLAUDE.local.md`.

## 6. The meta-rule

This file you're reading is itself a skill. If a procedure in
`AGENTS.md` or `CLAUDE.md` is longer than a paragraph, the right move
is almost always to extract it into a new skill under
`.claude/skills/<name>/` and leave a one-line pointer in the original
file. That's dogfooding Tinyhat's thesis — skills are the unit of
work — on the repo's own plumbing.

## 7. Non-negotiables

- Never edit a guidance file directly on `main` — every change goes
  through a PR.
- Never paste internal-only content into a committed file.
- Never leave a broken anchor link after renaming a section.
- Never let `CLAUDE.md` or `CLAUDE.local.md` drift past its ceiling.
