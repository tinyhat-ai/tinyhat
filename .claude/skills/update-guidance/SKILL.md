---
name: update-guidance
description: Use when editing any contribution-guidance file in the tinyhat repo — AGENTS.md, CLAUDE.md, CLAUDE.local.md(.example), or a SKILL.md under .claude/skills/. Covers where each piece of content belongs, anchor-link hygiene, the line-count budget per file, and the thin-harness-fat-skills rule that keeps eagerly-loaded files small.
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
| Cross-agent skill discovery layout | `docs/cross-agent-skills.md` | Compatibility matrix + drift-prevention rule. Cite from `AGENTS.md` rather than inlining. |

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

## 6. Cross-agent fan-out (when adding or editing a dev skill)

`.claude/skills/<name>/SKILL.md` is canonical. Codex discovers it
through the `.agents/skills` symlink (zero-drift). Cursor cannot read
`SKILL.md` at all and needs a `.cursor/rules/<name>.mdc` adapter whose
`description:` mirrors the canonical frontmatter description. Whenever
you add, rename, or change the `description:` of a dev skill:

- **New skill.** Drop a matching `.cursor/rules/<name>.mdc` adapter in
  the same PR. Use an existing adapter as the template — frontmatter
  is `description` (verbatim copy), `globs:` (empty), `alwaysApply:
  false`, body is a 6–10 line pointer at the canonical `SKILL.md`.
  Add the skill's row to the index in `AGENTS.md`.
- **Renamed skill.** Rename the `.cursor/rules/<name>.mdc` adapter and
  update the link target in its body. The `.agents/skills` symlink
  follows the canonical directory rename automatically.
- **Edited `description:`.** Copy the new value into the matching
  `.cursor/rules/<name>.mdc` in the same commit. Run the drift check
  in [`docs/cross-agent-skills.md`](../../../docs/cross-agent-skills.md)
  to confirm.
- **Deleted skill.** Delete the matching `.cursor/rules/<name>.mdc`
  adapter and remove the row from the `AGENTS.md` index.

The `.agents/skills` symlink and the matrix live in
[`docs/cross-agent-skills.md`](../../../docs/cross-agent-skills.md).
Don't inline the matrix into `AGENTS.md` or `CLAUDE.md` — link to it.

## 7. The meta-rule

This file you're reading is itself a skill. If a procedure in
`AGENTS.md` or `CLAUDE.md` is longer than a paragraph, the right move
is almost always to extract it into a new skill under
`.claude/skills/<name>/` and leave a one-line pointer in the original
file. That's dogfooding Tinyhat's thesis — skills are the unit of
work — on the repo's own plumbing.

## 8. Non-negotiables

- Never edit a guidance file directly on `main` — every change goes
  through a PR.
- Never paste internal-only content into a committed file.
- Never leave a broken anchor link after renaming a section.
- Never let `CLAUDE.md` or `CLAUDE.local.md` drift past its ceiling.
- Never add a dev skill under `.claude/skills/` without the matching
  `.cursor/rules/<name>.mdc` adapter and `AGENTS.md` index row in the
  same PR. Codex picks it up automatically via the symlink, but Cursor
  is invisible to it without an adapter.
