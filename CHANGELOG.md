# Changelog

All notable changes to Tinyhat are documented here. This file is
maintained by [release-please](https://github.com/googleapis/release-please)
— it reads Conventional Commit messages on `main` and produces a release
PR with the next version bump + changelog entry.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Pre-1.0, breaking changes bump the **minor** version, not major.

## [Unreleased]

### Added

- Initial v0 plugin scaffolding: `.claude-plugin/plugin.json`, three
  skills under `skills/` (`skill-audit`, `open-latest-audit`,
  `audit-history`), three scripts under `scripts/`
  (`gather_snapshot.py`, `render_report.py`, `routine.py`),
  self-contained HTML report with pie charts + dormant-surface +
  activity patterns, client-side filters for sessions and tools.
- Adaptive daily routine: at most one snapshot per local calendar date,
  fired opportunistically on skill load (no launchd, no cron).
- Archive retention (31 days) and an index page linking latest + every
  archived snapshot.
- Open-source contribution scaffolding: `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, PR template, issue templates,
  CI workflow, release workflow, dependabot, `.editorconfig`,
  `.gitattributes`, `pyproject.toml`, pre-commit config.
- Docs: `docs/user-flows.md`, `docs/artifacts.md`,
  `docs/architecture.md`, `docs/local-development.md`.
