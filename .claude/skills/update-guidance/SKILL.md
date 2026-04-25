---
name: update-guidance
description: Use when editing any contribution-guidance file in the tinyhat repo — AGENTS.md, CLAUDE.md, CLAUDE.local.md(.example), or a SKILL.md under .claude/skills/ or skills/. Covers where each piece of content belongs, anchor-link hygiene, the line-count budget per file, the thin-harness-fat-skills rule that keeps eagerly-loaded files small, and the SKILL.md frontmatter policy (which YAML keys to set, which to reject, how surfaces differ).
---

# update-guidance — edit policy files without breaking the pattern

Tinyhat's contribution docs follow the **thin harness, fat skills**
model: files loaded into every agent turn stay small; deep procedural
content lives in skills that load on demand. Before editing, figure out
where the change actually belongs.

## 1. Where does this change belong?

| What you're adding | Goes in | Why |
|---|---|---|
| Cross-agent policy (identity, commits, branches, PRs, versioning) | `AGENTS.md` | Canonical source of truth for every agent. |
| A step-by-step procedure for an operation | `.claude/skills/<op>/SKILL.md` | Fat skill; frontmatter loads eagerly, body on demand. |
| Claude-Code-specific tone, framing, scope guards | `CLAUDE.md` | Loaded per-turn by Claude Code. Keep tight. |
| Maintainer-private context | `CLAUDE.local.md` (gitignored) | Must not ship in the public repo. |
| Public-safe example of a local override | `CLAUDE.local.md.example` | Committed; no private URLs, no internal names. |
| New / changed `SKILL.md` frontmatter | `SKILL.md` header + [§ 8](#8-skillmd-frontmatter-policy) | Policy decides which YAML keys are required, optional, or rejected. |

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

## 8. SKILL.md frontmatter policy

The headline rules — full reasoning and the gbrain reconciliation
live in [`references/skill-frontmatter.md`](references/skill-frontmatter.md).
Read the reference the first time you author or audit a SKILL.md.

- **Required, both surfaces:** `name`, `description`. Set `name`
  even on packaged `skills/` files — Claude Code falls back to the
  directory name silently, but strict Agent Skills validators reject
  the omission.
- **Constraints:** `name` must match the directory and the regex
  `^[a-z0-9]+(-[a-z0-9]+)*$`, max 64 chars, no `anthropic`/`claude`
  substring. `description` is third-person, ≤1024 chars, and bakes
  routing phrases inline.
- **Optional, when warranted:** `argument-hint` for skills that take
  args; `allowed-tools` for skills that invoke scripts;
  `disable-model-invocation` for user-only commands. All
  Claude-Code-specific.
- **Rejected as top-level keys:** `triggers`, `tools`, `mutating`,
  `version`, `writes_pages`, `writes_to`. These are gbrain
  conventions Claude Code does not parse — `description`,
  `allowed-tools`, an ALL-CAPS gate prefix, and git history cover the
  same ground without dead frontmatter.
- **Tinyhat extensions go under `metadata.*`** per the Agent Skills
  spec's extension namespace recommendation. Do not invent new
  top-level keys.
- **Surface gating:** repo-scoped `.claude/skills/` keep frontmatter
  minimal (`name` + `description` unless a script forces more);
  packaged `skills/` add `argument-hint` + `allowed-tools` whenever
  the skill ships a runnable script.

Validate before pushing:

```bash
python3 scripts/validate_skill_frontmatter.py
```

CI's `lint` job runs the same script, so a header that drifts past
the policy fails the build.
