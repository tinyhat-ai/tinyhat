# Contributing to Tinyhat

Thanks for wanting to contribute. Tinyhat is now the public OpenClaw
platform plugin package for Tinyhat-managed Computers. This guide covers
the public workflow; the detailed agent/bot policy lives in
[AGENTS.md](AGENTS.md).

## Branches And PRs

The `main` branch is protected:

- Direct pushes to `main` are blocked.
- Every change goes through a pull request.
- Linear history is required.
- One approving review is required before merge.
- The most recent push must be approved by someone other than the pusher.
- PR conversations must be resolved before merge.

Create a focused branch for one logical change. Maintainers and bots with
write access may branch directly in this repo; external contributors should
fork first.

## Commits

Use Conventional Commits:

```text
feat(plugin): add platform status tool
fix(skills): clarify Telegram secret entry
docs: explain runtime boundary
ci: validate OpenClaw package metadata
```

The PR title should also be a Conventional Commit because release tooling
uses it for the squash commit and changelog.

AI agents contributing under bot identities should follow
[AGENTS.md](AGENTS.md) and the repo-local skills under
[`.agents/skills/`](.agents/skills).

## Local Checks

Prereqs:

- Python 3.9+.
- Node.js 18+ for syntax checking the JavaScript plugin entrypoint.

Run the checks that match your change:

```bash
git diff --check
python3 scripts/check_dev_skills.py
bash .github/scripts/check_packaging.sh
python3 scripts/validate_openclaw_package.py
python3 -m compileall -q scripts
node --check src/index.js
pipx run ruff check .
pipx run ruff format --check .
```

See [docs/local-development.md](docs/local-development.md) for the
short development loop and manual OpenClaw smoke-test guidance.

## Scope

This repo owns the OpenClaw plugin manifest, JavaScript tool plugin,
default injected skills, public capability docs, and release metadata.
It does not own Tinyhat backend endpoints, Computer provisioning,
OpenClaw runtime boot/supervision, tenant secrets, or private
deployment details.

Do not commit tenant secrets, signed Mini App URLs, private backend
URLs, local machine paths, or private Tinyloop docs.

## Questions

- Open an issue using the bug report or feature request template.
- Suspected security issue: do not open a public issue. See
  [SECURITY.md](SECURITY.md).
- General contact: `tinyhat@tinyloop.co`.

By participating, you agree to uphold our
[Code of Conduct](CODE_OF_CONDUCT.md).
