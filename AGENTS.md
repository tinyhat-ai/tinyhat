# AGENTS.md — Contribution policy

Canonical policy for humans and AI agents contributing to this repo.
Agent-specific files (`CLAUDE.md`) defer here and do not duplicate.

**Agents currently provisioned on the maintainer's machine:** Claude
Code, Codex. The maintainer onboards new agents via the
[`add-agent`](.claude/skills/add-agent/SKILL.md) skill.

## External contributors — the short version

Thanks for wanting to contribute. Here's all you actually need:

1. Fork, branch, commit, push, open a PR against `main`.
2. Use [Conventional Commits](https://www.conventionalcommits.org) for the
   commit subject if you can — e.g. `fix: typo in README`. Not a hard
   requirement for first-time contributors.
3. Keep changes atomic:
   1. One logical change per commit.
   2. One related thread per PR.
   3. Explain the why, not just the what.
   4. Split unrelated work before asking for review.

That's it. The dense policy below is plumbing for the AI agents the
maintainer runs under dedicated bot identities. You can skip it.

## How this repo works — thin harness, fat skills

We dogfood Tinyhat's thesis on our own contribution plumbing: every
non-trivial procedure is a **skill** under [`.claude/skills/`](.claude/skills).
Each skill's frontmatter (`name`, `description`) loads eagerly so the
resolver can route intent to it; the body loads only when the skill is
invoked. That keeps the files in every turn's context tight
(`AGENTS.md`, `CLAUDE.md`) and the procedural detail
rich where it actually needs to be.

Agents without native skill resolution (Cursor, Codex, anything reading
`AGENTS.md` directly) should treat the skills index below as a directory
and open the relevant `SKILL.md` before executing the operation.

## Skills index — contribution operations

| Operation | Skill | When to invoke |
|---|---|---|
| Make a commit | [`commit`](.claude/skills/commit/SKILL.md) | Before every commit, especially the first on a fresh clone. Covers bot-identity preflight, signing, Conventional Commits. |
| Open a pull request | [`open-pr`](.claude/skills/open-pr/SKILL.md) | After commits are on a branch, before `gh pr create`. Covers branch naming, PR template, review routing, no-self-merge. |
| Cut a release | [`release`](.claude/skills/release/SKILL.md) | Reviewing or merging a release-please PR, smoke-testing a published release, or rolling one back. Covers the pre-1.0 versioning policy and the manual-release escape hatch. |
| Onboard a new agent | [`add-agent`](.claude/skills/add-agent/SKILL.md) | Before a new coding agent touches this repo. Covers machine-user provisioning, SSH alias, identity-table row, `.gitignore` rules. |
| Edit a guidance file | [`update-guidance`](.claude/skills/update-guidance/SKILL.md) | When changing `AGENTS.md`, `CLAUDE.md`, any `SKILL.md`, or `CLAUDE.local.md*`. Covers where each piece belongs, line budgets, anchor hygiene. |
| Propose a roadmap change | [`propose-roadmap`](.claude/skills/propose-roadmap/SKILL.md) | When moving an item between `roadmap/` files, adding a new candidate, or flagging something for rejection. Covers PR format and the one-move-per-PR rule. |
| Reset local plugin state for a fresh install test | [`dev-reset`](.claude/skills/dev-reset/SKILL.md) | Before a contributor smoke-tests the first-run flow or `claude --plugin-dir "$(pwd)"` iteration. Wipes every Tinyhat byte + plugin registration the local machine holds; dry-run by default. Contributor-only — never packaged. |

When a skill's `description` matches what you're about to do, invoke it
instead of improvising. When in doubt, start with `update-guidance`.

## Non-negotiables (agent-only)

These apply to AI agents acting under a bot identity. Human
contributors can ignore this section.

- **Never commit as the maintainer.** Agents commit under a dedicated
  machine-user identity with SSH signing, injected inline via `-c`
  overrides on every `git commit`. The repo's local git config is
  always the maintainer's identity; agents never set
  `git config --local user.*` or signing fields. See the `commit`
  skill for the full pattern.
- **Never push to `main`.** Every change goes through a PR from a
  branch named `<agent>/<short-topic>`.
- **Agents never self-merge.** Only `CODEOWNERS` merges an agent PR.
- **Never use `--no-verify` or `[skip ci]`** without the maintainer's
  explicit OK. Never commit keys, tokens, or credentials. Never reuse
  one agent's signing key on another agent.

## Atomic commits and PRs

Atomic commits are the default expectation for agent work. A commit is
atomic when a future reviewer can answer "what does this do?" in one
sentence, the diff builds or documents one coherent state, and the
message body explains the constraint, failure mode, or tradeoff that
made the change necessary.

- **One logical change per commit.** Code plus its tests can be one
  commit; a refactor plus a feature plus a CI bump cannot.
- **One related thread per PR.** Multiple commits may ship together
  only when they are all needed to tell one reviewable story. If two
  commits could be reviewed, reverted, or released independently, split
  them into separate PRs or a stack of PRs.
- **Messages explain why.** The subject summarizes what changed. The
  body explains why now, what alternative was rejected, or what bad
  future state the commit prevents.
- **When in doubt, split.** Agents pay little cost for small branches;
  reviewers pay real cost for grab-bag diffs. Use stacked PRs when
  small dependent changes must land in order.

Anti-patterns: `misc fixes`, `bulk update docs`, `address review
feedback` as a landed commit subject, and any PR mixing unrelated
feature, refactor, release, documentation, or CI work.

## Commit and versioning conventions

- **Conventional Commits** for commit subjects: `<type>(<scope>): <subject>`,
  imperative, <72 chars. Types: `feat`, `fix`, `docs`, `refactor`, `test`,
  `chore`, `ci`, `build`. Breaking: `!` or `BREAKING CHANGE:` footer.
  Strongly encouraged for everyone; strictly required for agent commits.
- **Atomicity:** see [Atomic commits and PRs](#atomic-commits-and-prs).
- **Versioning:** [SemVer 2.0](https://semver.org), tags `vX.Y.Z`.
  Maintainer creates tags on merged `main`. Pre-1.0, breaking changes
  bump **minor**, not major.

## Local override files

`CLAUDE.local.md` (gitignored) holds internal maintainer context that
must not ship publicly. Never echo its contents into committed files,
commit messages, PR bodies, issues, or external systems.
`CLAUDE.local.md.example` is a sanitized template and must not name
private resources. External contributors can ignore both.
