# Contributing to Tinyhat

Thanks for wanting to contribute. This guide covers the workflow and the rules.
For the broader contribution policy — including the bot-identity setup used by
AI agents that commit under their own identities — see [AGENTS.md](AGENTS.md).

## Ground rules (branch protection on `main`)

The `main` branch is protected by a GitHub ruleset:

- Direct pushes to `main` are blocked. Every change goes through a Pull Request.
- Linear history is required. Only **Squash** and **Rebase** merges are allowed.
- 1 approving review is required before merging.
- Stale approvals are dismissed when new commits are pushed.
- The most recent push must be approved by someone other than the pusher — no self-merges.
- All PR conversations must be resolved before merge.
- Force pushes and branch deletion are blocked.

## The workflow

### 1. Fork (external contributors) or branch (maintainers with write)

External contributors: fork the repo, then clone your fork and create a branch.
Maintainers and bots with push access: create a feature branch directly.

### 2. Name your branch

Use a short, descriptive kebab-case branch name prefixed by the change type:

- `feat/<topic>` — a new feature
- `fix/<topic>` — a bug fix
- `docs/<topic>` — documentation only
- `chore/<topic>` — tooling, CI, deps
- `refactor/<topic>` — no behavior change
- `test/<topic>` — test-only changes

AI agents contributing under a bot identity instead use `<bot-name>/<topic>` per
[AGENTS.md](AGENTS.md) — e.g. `claude-code-bot/v0-local-scanner`.

### 3. Commit with Conventional Commits

Format: `<type>(<optional scope>): <subject>`, imperative, under 72 chars.
Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `build`.
Breaking changes: append `!` to the type or add a `BREAKING CHANGE:` footer.

```
feat(skills): add audit-history skill for browsing past reports
fix(scanner): handle Z-suffix ISO timestamps on macOS
docs: clarify the plugin vs script-only testing paths
```

The PR title must also be a Conventional Commit — it becomes the squash
commit message on `main`, and release tooling reads it to bump the version.

### 4. Sign your commits (DCO — optional)

We don't require a signed-off-by line, but `git commit -s` (Developer
Certificate of Origin) is welcome. AI agents commit with SSH-signed
commits under their own bot identity — see the `commit` skill under
`.claude/skills/commit/SKILL.md`.

### 5. Run things locally before pushing

**Prereqs:** Python 3.9+ on your `PATH`.

```bash
# Run the scripts directly against your real local Claude data
python3 scripts/gather_snapshot.py
python3 scripts/render_report.py --open

# Exercise the plugin end-to-end in a fresh Claude Code session
claude --plugin-dir "$(pwd)"

# Lint + format check (same as CI)
pipx run ruff check .
pipx run ruff format --check .
```

Detailed dev loop: **[docs/local-development.md](docs/local-development.md)**.

### 6. Open the PR

Fill out the [pull request template](.github/pull_request_template.md)
completely. Link the issue it closes (`Closes #123`). Describe what you
tested and attach screenshots for UI changes.

### 7. Review cycle

- A CODEOWNER reviews. Respond to feedback in the thread — don't close
  threads until the reviewer marks them resolved.
- Pushing new commits dismisses stale approvals. Don't panic — the
  reviewer will re-approve.
- When the PR is green (CI passing, 1 approval, all conversations
  resolved), a maintainer squashes or rebases it onto `main`.

## Merge policy

Only **Squash** and **Rebase** are enabled. Squash is the default — the
PR title becomes the commit message on `main`, so write it well.

## Reproducing CI locally

CI runs on every PR. Required jobs:

| Job | What it does | Reproduce locally |
|---|---|---|
| `lint` | `ruff check .` + `ruff format --check .` | `pipx run ruff check . && pipx run ruff format --check .` |
| `smoke` | Imports every script, runs `gather_snapshot.py` + `render_report.py --index-only` against a scratch `--home-root`, asserts exit 0 | `python3 -m compileall scripts && python3 scripts/gather_snapshot.py --output /tmp/snap.json && python3 scripts/render_report.py --snapshot /tmp/snap.json --home-root /tmp/tinyhat-ci --index-only` |

There's no unit-test suite yet — v0 is scaffolding. When tests land,
they'll be listed here.

## Pre-commit (optional but nice)

If you want lint/format to run automatically before every commit, install
[pre-commit](https://pre-commit.com/) and run:

```bash
pipx install pre-commit
pre-commit install
```

Our `.pre-commit-config.yaml` runs the same checks as CI.

## Questions / discussion

- Open an issue using the [bug report](.github/ISSUE_TEMPLATE/bug_report.yml)
  or [feature request](.github/ISSUE_TEMPLATE/feature_request.yml) template.
- Suspected security issue: **do not open a public issue.** See
  [SECURITY.md](SECURITY.md).
- General contact: `tinyhat@tinyloop.co`.

## Community

By participating, you agree to uphold our
[Code of Conduct](CODE_OF_CONDUCT.md).
