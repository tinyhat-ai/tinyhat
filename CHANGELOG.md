# Changelog

All notable changes to Tinyhat are documented here. This file is
maintained by [release-please](https://github.com/googleapis/release-please)
— it reads Conventional Commit messages on `main` and produces a
release PR with the next version bump + changelog entry.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Pre-1.0 policy:** we bump **minor** for new features and **patch**
for fixes. Breaking changes stay in minor bumps until we explicitly
ship `1.0.0`. Release-please is configured to honor this
(`bump-minor-pre-major: true`, `bump-patch-for-minor-pre-major: true`).

## [0.1.7](https://github.com/tinyhat-ai/tinyhat/compare/v0.1.6...v0.1.7) (2026-04-23)


### Features

* **dev:** Add internal dev-reset skill for fresh first-run testing ([#59](https://github.com/tinyhat-ai/tinyhat/issues/59)) ([2bc7647](https://github.com/tinyhat-ai/tinyhat/commit/2bc7647e251d8232f1c404bdc90d3719c0481fdb))


### Bug Fixes

* **paths:** Forward CLAUDE_PLUGIN_DATA from skill body into python3 env ([#61](https://github.com/tinyhat-ai/tinyhat/issues/61)) ([1ecaccf](https://github.com/tinyhat-ai/tinyhat/commit/1ecaccf8dc4332b0544202db646a8c125d687ac2))

## [0.1.6](https://github.com/tinyhat-ai/tinyhat/compare/v0.1.5...v0.1.6) (2026-04-23)


### Bug Fixes

* **paths:** Reconcile split-brain plugin-data homes (closes [#52](https://github.com/tinyhat-ai/tinyhat/issues/52)) ([#54](https://github.com/tinyhat-ai/tinyhat/issues/54)) ([685f4b9](https://github.com/tinyhat-ai/tinyhat/commit/685f4b93343e83d85007fe3e7809fdb045aefa86))

## [0.1.5](https://github.com/tinyhat-ai/tinyhat/compare/v0.1.4...v0.1.5) (2026-04-23)


### Bug Fixes

* **audit:** Improve first-run report flow ([#49](https://github.com/tinyhat-ai/tinyhat/issues/49)) ([6e9f055](https://github.com/tinyhat-ai/tinyhat/commit/6e9f055748920ce36d49a1ae042a3949f3d598b2))

## [0.1.4](https://github.com/tinyhat-ai/tinyhat/compare/v0.1.3...v0.1.4) (2026-04-23)


### Features

* **audit:** Chat summary + persisted JSONs instead of auto-opening HTML ([#45](https://github.com/tinyhat-ai/tinyhat/issues/45)) ([39471c4](https://github.com/tinyhat-ai/tinyhat/commit/39471c41718d2a5c7f6179cf85c70064e0a12830))

## [0.1.3](https://github.com/tinyhat-ai/tinyhat/compare/v0.1.2...v0.1.3) (2026-04-23)


### Features

* **roadmap:** Add public roadmap + propose-roadmap skill (closes [#32](https://github.com/tinyhat-ai/tinyhat/issues/32)) ([#33](https://github.com/tinyhat-ai/tinyhat/issues/33)) ([d7bd122](https://github.com/tinyhat-ai/tinyhat/commit/d7bd1222bf64913a452c5061fc0e52d40d5cf5a3))


### Bug Fixes

* **skills:** Resolve bundled script paths via `${CLAUDE_SKILL_DIR}` so `/tinyhat:audit`, `/tinyhat:routine`, and `/tinyhat:history` work on every install, not just the maintainer's. `${CLAUDE_PLUGIN_ROOT}` is only set inside `!`-prefixed load-time blocks and was silently empty in the non-`!` Bash calls the agent actually ran, which broke `gather_snapshot.py` and friends with `No such file or directory` (closes [#36](https://github.com/tinyhat-ai/tinyhat/issues/36)) ([#41](https://github.com/tinyhat-ai/tinyhat/issues/41)) ([79163cd](https://github.com/tinyhat-ai/tinyhat/commit/79163cd44b304bb63a251f03c426c3283a0a1d98))

## [0.1.2](https://github.com/tinyhat-ai/tinyhat/compare/v0.1.1...v0.1.2) (2026-04-23)


### Bug Fixes

* Add marketplace manifest so the plugin can be installed (closes [#11](https://github.com/tinyhat-ai/tinyhat/issues/11)) ([#12](https://github.com/tinyhat-ai/tinyhat/issues/12)) ([c0da383](https://github.com/tinyhat-ai/tinyhat/commit/c0da383f95bf50848d2b588f736647dd7d160ca0))

## [0.1.1](https://github.com/tinyhat-ai/tinyhat/compare/v0.1.0...v0.1.1) (2026-04-23)


### Features

* V0 local scanner plugin + open-source scaffolding ([#2](https://github.com/tinyhat-ai/tinyhat/issues/2)) ([855ea2a](https://github.com/tinyhat-ai/tinyhat/commit/855ea2ad0aba048660c19d80ff02762bcd98d839))

## [Unreleased]

### Added

- Initial v0 plugin scaffolding: `.claude-plugin/plugin.json`, four
  skills under `skills/` (`audit`, `open`, `history`, `routine`),
  three scripts under `scripts/` (`gather_snapshot.py`,
  `render_report.py`, `routine.py`), self-contained HTML report with
  pie charts, activity patterns, client-side filters for sessions
  and tools, and a browsable archive index.
- Adaptive daily refresh — at most one snapshot per local calendar
  date, triggered opportunistically on skill load (no launchd, no
  cron).
- Archive retention (31 days) and an index page linking latest + every
  archived snapshot.
- Open-source contribution scaffolding: `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, PR template, issue templates,
  CI workflow, release workflow (pinned pre-1.0), dependabot,
  `.editorconfig`, `.gitattributes`, `pyproject.toml`, pre-commit
  config.
- Docs: `docs/user-flows.md`, `docs/artifacts.md`,
  `docs/architecture.md`, `docs/local-development.md`.

### Changed

- Reset from accidental `v1.0.0` (auto-released by an unconfigured
  release-please run) back to pre-1.0 versioning. First public
  release will be `0.1.0`.
