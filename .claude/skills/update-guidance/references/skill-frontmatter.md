# SKILL.md frontmatter — Tinyhat header policy

This is the long-form policy. The headline rules live in
[`SKILL.md` § 8](../SKILL.md#8-skillmd-frontmatter-policy); read that
first. Come here when you need the *why*, the field-by-field reasoning,
or the gbrain-vs-Claude-Code reconciliation.

## TL;DR

- Required on every `SKILL.md`: `name`, `description`. Nothing else is
  required by anyone.
- Recommended-when-warranted: `argument-hint`, `allowed-tools`,
  `disable-model-invocation`. All Claude-Code-only.
- Reject: `triggers`, `tools`, `mutating`, `version` as top-level keys.
  These are gbrain conventions Claude Code does not parse — adopting
  them costs maintenance for zero runtime benefit. The information they
  carry belongs in `description`, `allowed-tools`, or the body.
- Tinyhat-specific extension keys go under `metadata.*`, per the Agent
  Skills spec recommendation.

## What different ecosystems actually parse

Two specs govern an `SKILL.md` header. They overlap on `name` +
`description` and diverge on everything else.

| Source | Fields parsed | Behavior on unknown fields |
|---|---|---|
| Agent Skills spec ([agentskills.io/specification](https://agentskills.io/specification)) | Required `name`, `description`. Optional `license`, `compatibility`, `allowed-tools` (experimental), `metadata` (extension namespace). | Not strict; `metadata.*` is the documented extension point. |
| Anthropic platform (`platform.claude.com/.../agent-skills/best-practices`) | Required `name`, `description`. | Silent on unknowns. |
| Claude Code ([code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills)) | Adds optional `when_to_use`, `argument-hint`, `arguments`, `disable-model-invocation`, `user-invocable`, `allowed-tools`, `model`, `effort`, `context`, `agent`, `hooks`, `paths`, `shell`. | Silently ignores unknowns (no doc warning). |
| Cursor `.cursor/rules/*.mdc` ([cursor.com/docs/context/rules](https://cursor.com/docs/context/rules)) | `description`, `globs`, `alwaysApply`. **Different file extension; does not read `SKILL.md`.** | n/a |
| OpenAI Codex ([academy.openai.com/.../skills](https://academy.openai.com/public/resources/skills)) | No SKILL.md frontmatter contract. Codex reads `AGENTS.md`. | n/a |

So portability across surfaces is decided almost entirely by `name` +
`description`. Everything else is Claude-Code-only or Anthropic-only —
and that is fine, because Tinyhat's distribution surface is Claude
Code via `/plugin install`.

## Field-by-field policy

### `name` (required, both surfaces)

Stable machine-readable id for the skill.

- Constraints (Anthropic + Agent Skills): max 64 chars, lowercase
  letters / digits / hyphens, must not start or end with a hyphen,
  cannot contain `anthropic` or `claude`, cannot match an XML tag.
- Must equal the directory name. The Agent Skills validator enforces
  this; Claude Code falls back silently if missing, which is what
  tripped the four packaged skills before #82.
- No plugin-namespace prefix (the `tinyhat:` you see in
  `/tinyhat:audit` is added by Claude Code at load time from
  `.claude-plugin/plugin.json`, not by the skill).

### `description` (required, both surfaces)

Discovery text. Pre-loaded into the system prompt and used by Claude to
decide when to invoke.

- Hard cap: 1024 characters. (Claude Code truncates the
  `description` + `when_to_use` listing at 1536.)
- Third-person, present-tense imperative — describe what the skill
  *does* and *when to use it*, not what the agent should do.
- Bake routing phrases into the description rather than splitting them
  into a `triggers:` field. Claude Code routes off the description; a
  separate `triggers:` key is unparsed dead weight.
- For destructive or restricted skills, lead with an ALL-CAPS gate
  word so the discovery surface makes the danger obvious. The
  `dev-reset` skill leads with `INTERNAL DEV ONLY —` and the CI
  packaging-guard enforces that prefix; copy that pattern for any new
  destructive skill.

### `argument-hint` (optional)

Display-only string shown next to the slash command in autocomplete.

- Use when the skill takes positional or flag arguments and an end
  user would not guess them.
- Format: square-bracket flags (`[--archive] [--open]`) or
  pipe-separated subcommands (`status | on | off | where | clear`).
- Skip when the skill takes no args. Adding a hollow hint adds noise
  to the autocomplete and forces a re-edit later.

### `allowed-tools` (optional)

Pre-approves the listed tools while the skill is active so the user is
not prompted on every invocation. **Not a sandbox** — other tools
remain callable, governed by the harness permission settings.

- List only the tools the skill actually invokes from inline `` !`` ``
  blocks or from documented Bash/Read/Write usage. Over-listing widens
  the trust boundary for no benefit.
- Format mirrors the Claude Code permission grammar:
  `Bash(python3 *) Read Write` — space-separated, parameter globs
  inside parentheses.

### `disable-model-invocation` (optional)

Set `true` to make the skill user-invocable only via `/<name>` and
prevent the model from auto-loading it. Use sparingly — it disables
the routing surface that makes a skill discoverable.

### `model`, `effort`, `context`, `agent`, `paths`, `hooks`, `shell` (optional)

Claude-Code-specific runtime knobs. None of Tinyhat's current skills
use them. If you reach for one, document the reason in the `SKILL.md`
body in one sentence so a future reviewer doesn't strip it as
boilerplate.

### `metadata.*` (optional, extension namespace)

The Agent Skills spec carves `metadata` out as a string→string map for
client-specific extensions. If Tinyhat ever needs to track ownership,
review dates, or contract versions on a skill, namespace them here:

```yaml
metadata:
  owner: tinyhat-maintainers
  contract_version: 1
  last_reviewed: 2026-04-25
```

Do **not** promote any of these to top-level keys. Top-level extension
keys risk colliding with future Anthropic / Claude Code additions.

## Rejected gbrain conventions

[`gbrain`](https://github.com/garrytan/gbrain) ships every skill with
`triggers`, `tools`, `mutating`, and `version` in the header. Those
keys are consumed by gbrain's own conformance tests and its OpenClaw
harness — Claude Code's loader ignores them. Tinyhat does not adopt
any of the four. The reasoning per field:

| gbrain key | Why Tinyhat rejects it | Where the information goes instead |
|---|---|---|
| `triggers` (list of phrases) | Claude Code routes from `description`; a parallel `triggers:` list duplicates that text and silently drifts. The MECE invariant gbrain enforces against it does not exist in Claude Code. | Inline in `description` — most Tinyhat skills already do this (e.g. `Triggers on "..."`). |
| `tools` (capability advertisement) | Conflated with Claude Code's `allowed-tools` (which is a permission list, not a capability list). Two keys with similar names cause confusion. | If you mean *permissions*, use `allowed-tools`. If you mean *what the skill needs*, write a sentence in the body. |
| `mutating` (boolean) | Not enforced anywhere; readers ignore booleans they don't recognize. | Lead the `description` with an ALL-CAPS gate (`INTERNAL DEV ONLY`, `DESTRUCTIVE —`) and put the destructive scope in the body. The `dev-reset` skill is the canonical example. |
| `version` (semver) | Claude Code never reads it; git history is the authoritative version record; release-please tags the plugin as a whole. A skill-level version diverges from both. | If a contract version is genuinely needed (e.g. a script-API change), put it under `metadata.contract_version` so it cannot collide with a future top-level key. |

`writes_pages` and `writes_to`, also from gbrain, are rejected for the
same reason — they encode a filing audit specific to gbrain's brain
ops; Tinyhat has no equivalent surface to enforce against.

## Surface gating

Two surfaces ship `SKILL.md` files in this repo, with slightly
different defaults.

### `.claude/skills/` (development skills, repo-scoped)

Loaded automatically when an agent works inside this checkout. The
audience is contributors, not end users.

- Required: `name`, `description`.
- Optional but discouraged for these skills: `argument-hint`,
  `allowed-tools`. Add only when the skill genuinely takes args or
  invokes scripts (`dev-reset` is the only current example).
- Do not add `disable-model-invocation: true` here — agents need to
  route to these skills automatically.

### `skills/` (packaged plugin skills, end-user-facing)

Bundled into `/plugin install tinyhat@tinyloop`. Audience is real
users of any plugin install.

- Required: `name` (Tinyhat policy goes beyond Claude Code's
  directory-name fallback so strict Agent Skills validators stay
  green), `description`.
- Recommended: `argument-hint` for any skill that takes args;
  `allowed-tools` for any skill that calls scripts. End users rely on
  these for autocomplete + permission preflight.
- Forbidden: any reference to `dev-reset` or other dev-only scripts
  (CI's `.github/scripts/check_packaging.sh` enforces this).

## Validation

Run the stdlib-only checker before opening a PR:

```bash
python3 scripts/validate_skill_frontmatter.py
```

It enforces:

1. The frontmatter block exists and is well-formed (`---`-fenced YAML
   at the top of the file).
2. `name` and `description` are present.
3. `name` matches the directory name and the Anthropic regex
   (`^[a-z0-9]+(-[a-z0-9]+)*$`, ≤64 chars, no `anthropic`/`claude`
   substring).
4. `description` is ≤1024 characters.
5. No top-level `triggers`, `tools`, `mutating`, `version`,
   `writes_pages`, or `writes_to` keys leak in. (Use `metadata.*` if
   you really need a custom field.)

CI runs the validator in the `lint` job, so a header that drifts past
the policy fails the build. To wire it into pre-commit, add this hook
locally:

```yaml
- repo: local
  hooks:
    - id: validate-skill-frontmatter
      name: validate SKILL.md frontmatter
      entry: python3 scripts/validate_skill_frontmatter.py
      language: system
      pass_filenames: false
      files: ^(\.claude/)?skills/.*/SKILL\.md$
```

The validator deliberately does not use `pyyaml` so the smoke matrix
and end-user installs stay dep-free, matching `pyproject.toml`'s
"stdlib only" stance.

## Audit log — where the existing skills landed

A pre-#82 audit caught two classes of drift:

- All four packaged skills (`skills/audit`, `skills/history`,
  `skills/open`, `skills/routine`) omitted `name`. Fixed in #82 —
  they now declare `name: <dir>` so Agent-Skills-strict validators
  pass.
- Every `.claude/skills/*/SKILL.md` already conforms (`name` +
  `description`; `dev-reset` adds `argument-hint` + `allowed-tools`,
  which is appropriate for the only repo-scoped skill that actually
  runs a script).

When you add or edit a skill, run the validator and append a one-line
audit entry to the relevant PR description rather than expanding this
section — the policy is the durable artifact; the audit log lives in
git history.
