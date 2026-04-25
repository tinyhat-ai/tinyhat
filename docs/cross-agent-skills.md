# Cross-agent skill compatibility

Tinyhat's development skills (`.claude/skills/<name>/SKILL.md`) guide
contribution operations like commits, PRs, releases, and onboarding.
The maintainer uses Claude Code today and Codex in parallel; Cursor is
a likely future entrant. This doc records how each tool finds the same
skills, what's canonical, what's a generated view, and how we keep
drift to zero.

## TL;DR

| Tool | Discovery path (project) | Reads `SKILL.md`? | What we ship | Maintenance per skill |
|---|---|---|---|---|
| Claude Code | `.claude/skills/<name>/SKILL.md` | yes (canonical) | the canonical files | n/a — canonical |
| Codex | `.agents/skills/<name>/SKILL.md` + top-level `AGENTS.md` | yes | `.agents/skills` is a **symlink** to `.claude/skills` | none — symlink covers it |
| Cursor | `.cursor/rules/*.mdc` + top-level `AGENTS.md` | **no** — only `.mdc` and `AGENTS.md` | a thin `.cursor/rules/<name>.mdc` adapter pointing at the canonical `SKILL.md` | one short `.mdc` per skill |

Canonical source of truth is `.claude/skills/<name>/SKILL.md`. The
symlink and adapters are generated views — never edit them directly,
edit the canonical file and (for Cursor) refresh the description in the
adapter.

## Compatibility matrix

| Aspect | Claude Code | Codex | Cursor |
|---|---|---|---|
| Project discovery | `.claude/skills/<name>/SKILL.md` (also nested in subdirs) | `.agents/skills/<name>/SKILL.md` walked from CWD up to repo root + `AGENTS.md` from project root down | `.cursor/rules/*.mdc` (any depth under `.cursor/rules/`) + top-level `AGENTS.md` |
| User discovery | `~/.claude/skills/` | `~/.agents/skills/`, `~/.codex/AGENTS.md` | UI-managed user rules |
| Frontmatter fields | `name`, `description`, `allowed-tools`, `paths`, `disable-model-invocation`, `user-invocable`, `model`, `hooks`, `arguments`, … | `name`, `description` (sidecar `agents/openai.yaml` for tool deps) | `description`, `globs`, `alwaysApply` |
| Activation modes | progressive disclosure; `/<name>`; `paths` glob auto-load; `disable-model-invocation` for manual-only | progressive disclosure; `/skills`; `$name`; description match | Always Apply / Apply Intelligently (description) / Apply to Specific Files (`globs`) / Apply Manually (`@rule`) |
| Tool restrictions | `allowed-tools` pre-approves (does not deny) | sidecar `agents/openai.yaml` for MCP deps | none documented |
| Mutating-action metadata | none (workaround: `disable-model-invocation: true`) | none documented | none documented |
| Honors top-level `AGENTS.md` | no — Claude Code reads `CLAUDE.md` | yes — primary instructions file | yes — auto-applied at project root |
| Validation tooling | follows the [Agent Skills spec](https://agentskills.io/specification); `skills-ref validate` | follows Agent Skills spec; `skills-ref validate` | no schema validator documented |

Sources: [Claude Code skills](https://code.claude.com/docs/en/skills),
[Codex AGENTS.md](https://developers.openai.com/codex/guides/agents-md),
[Codex skills](https://developers.openai.com/codex/skills),
[Cursor rules](https://cursor.com/docs/context/rules),
[agentskills.io](https://agentskills.io/specification). Verified April 2026.

## Why this layout

We considered four shapes. The chosen layout is the lightest one that
gives all three tools first-class, low-drift discovery:

- **Canonical at `.claude/skills/`** because Claude Code is the primary
  agent, that path matches the agentskills.io spec verbatim, and the
  existing skills are already there.
- **Symlink for Codex** because Codex's `.agents/skills/` discovery is
  identical in structure but lives at a different path. A symlink
  costs one filesystem entry, scales to every future skill for free,
  and cannot drift.
- **`.mdc` adapters for Cursor** because Cursor does not read
  `SKILL.md` files at all — only `.cursor/rules/*.mdc` and a top-level
  `AGENTS.md`. The adapter is a 6–10 line file whose body just tells
  Cursor's agent to open the canonical `SKILL.md`. Activation mode is
  "Apply Intelligently" (`alwaysApply: false` + populated description),
  so it loads only when the description matches the user's intent.
- **`AGENTS.md` index** carries a one-line description of every skill
  for any agent that auto-loads `AGENTS.md` (Codex, Cursor) or that
  reads a top-level pointer (everything else). The index is
  belt-and-suspenders coverage for non-Claude agents.

We rejected:

- **Generating duplicate `.agents/skills/<name>/SKILL.md` files**
  (Codex stub directories) — adds drift without benefit when a
  symlink works.
- **Moving the canonical to a neutral path** like `skills-shared/` —
  none of the three tools agree on a "neutral" location, and Claude
  Code's plugin tooling already targets `.claude/skills/`. The move
  would force every tool into adapter mode for no gain.
- **A dedicated generator script** — eight skills today, low velocity.
  The maintenance cost of one short `.mdc` per skill is below the
  cost of a script + lint + CI hook. Re-evaluate if the dev skill
  count grows past ~25.

## Drift prevention

The only fan-out point that can drift is the `description:` line in
each `.cursor/rules/<name>.mdc`. The rule:

> When you change a dev skill's `description:` in
> `.claude/skills/<name>/SKILL.md`, copy the new value into the
> matching `.cursor/rules/<name>.mdc` in the same commit.

This rule is enforced by the
[`update-guidance`](../.claude/skills/update-guidance/SKILL.md) skill's
checklist. To audit by hand:

```bash
for skill in .claude/skills/*/SKILL.md; do
  name=$(basename "$(dirname "$skill")")
  mdc=".cursor/rules/${name}.mdc"
  [[ -f "$mdc" ]] || { echo "missing adapter: $mdc"; continue; }
  diff <(awk '/^description:/{sub(/^description: */,""); print; exit}' "$skill") \
       <(awk '/^description:/{sub(/^description: */,""); print; exit}' "$mdc") \
    >/dev/null || echo "drift: $name"
done
```

The Codex symlink cannot drift by construction.

## Cross-platform note

The `.agents/skills` symlink works natively on macOS and Linux. On
Windows, git materializes symlinks as plaintext files containing the
target path unless symlink support is enabled (developer mode or
admin). Tinyhat is maintained on macOS; if a Windows contributor needs
Codex discovery, they can replace the symlink with a junction
(`mklink /J .agents\skills .claude\skills`) locally. The repo only
ships the symlink form.

## Validation

The `commit` skill is the canonical end-to-end test for this layout.
It is reachable through every supported path:

- Claude Code: `.claude/skills/commit/SKILL.md` (direct)
- Codex: `.agents/skills/commit/SKILL.md` via the symlink, or via the
  skills index in `AGENTS.md`
- Cursor: `.cursor/rules/commit.mdc` triggers on commit-related
  intent and instructs the agent to open
  `.claude/skills/commit/SKILL.md`

Each path resolves to the same content. Internal links inside the
canonical `SKILL.md` (e.g., `../add-agent/SKILL.md`) are unchanged and
still resolve correctly when the file is reached through the symlink.

## What this doc does NOT cover

- The packaged plugin skills under `skills/` (`audit`, `open`,
  `history`, `routine`). Those are end-user Claude Code skills shipped
  via the plugin marketplace; they are loaded by Claude Code's plugin
  loader, not by this cross-agent layout.
- User-level (machine-wide) skill installs. This doc is repo-local.
- A formal generator/CI lint. We may add one if the dev skill count
  outgrows manual maintenance.
