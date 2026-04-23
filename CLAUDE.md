# Claude Code — project context

Cross-agent policy lives in [`AGENTS.md`](AGENTS.md). Read it before
your first commit. This file only holds Claude-Code-specific context.

If `CLAUDE.local.md` exists next to this file, Claude Code also loads
it. It is gitignored and internal-only — see
[Local override files](AGENTS.md#local-override-files).

## Thin harness, fat skills — use the skills

Procedural detail for contribution operations (commit, open a PR,
onboard a new agent, edit guidance files) lives in
[`.claude/skills/`](.claude/skills). Each skill's `SKILL.md`
frontmatter loads eagerly, the body only when invoked. **When a skill's
description matches what you're doing, invoke it** instead of
improvising — that's the pattern we're dogfooding and the reason this
file stays short. See the [skills index in AGENTS.md](AGENTS.md#skills-index--contribution-operations).

## Product

Tinyhat is a Claude Code plugin for skill lifecycle observability:
which skills an agent actually uses, which ones might be missing, what
to add, what to retire. A later v1 direction explores cost and
replay-driven model comparison, but v0 is lifecycle visibility.

**Pre-alpha, design phase, no application code yet.** Before adding
any, confirm with the maintainer that the design is locked for the
area you're touching.

## Principles

- **Docs-first.** When in doubt, update a doc; don't write code.
- **Skill-first.** Product and plumbing. Code will sit alongside a
  `SKILL.md` when it lands.
- **Runs locally.** No HTTP endpoints, databases, or sign-in in v0.
- **Agentic UX, not GUI.** No dashboards, no forms.

## Markdown conventions

- Markdown only (no MDX). ATX headings (`#`), not `===` underlines.
- One sentence per line in prose — keeps diffs reviewable.
- Max two levels of nested bullets. Trailing newline on every file.

## Out of scope right now

Pause and confirm with the maintainer before: scaffolding a JS/Python
project, adding a plugin manifest, CI workflows, release automation,
dependency management, issue templates, a docs site generator.
