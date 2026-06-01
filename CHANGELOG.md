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

## Unreleased

### Changed

- Reset the package from the retired Claude Code skill-audit plugin into
  the public Tinyhat OpenClaw platform plugin, with manifest, tools,
  default skill, docs, roadmap, validation, and release metadata tracked
  by [#93](https://github.com/tinyhat-ai/tinyhat/issues/93).

## [0.2.3](https://github.com/tinyhat-ai/tinyhat/compare/v0.2.2...v0.2.3) (2026-06-01)


### Features

* **skills:** Add software update guidance ([#111](https://github.com/tinyhat-ai/tinyhat/issues/111)) ([d9b6ce1](https://github.com/tinyhat-ai/tinyhat/commit/d9b6ce19d426e5308abad533493556909d60d723))

## [0.2.2](https://github.com/tinyhat-ai/tinyhat/compare/v0.2.1...v0.2.2) (2026-05-29)


### Bug Fixes

* **skills:** Send the ChatGPT settings screenshot inline + split the device code into its own bare bubble (closes [#108](https://github.com/tinyhat-ai/tinyhat/issues/108)) ([#109](https://github.com/tinyhat-ai/tinyhat/issues/109)) ([b48b27c](https://github.com/tinyhat-ai/tinyhat/commit/b48b27ca8fc1d8528f6af4c319829f34d7302afe))

## [0.2.1](https://github.com/tinyhat-ai/tinyhat/compare/v0.2.0...v0.2.1) (2026-05-29)


### Features

* **skills:** Add tinyhat-subscriptions for ChatGPT BYO device-code linking ([#106](https://github.com/tinyhat-ai/tinyhat/issues/106)) ([2aa19d6](https://github.com/tinyhat-ai/tinyhat/commit/2aa19d6dee57c9e78fef47d6ef664aa0af5d8a39))

## [0.2.0](https://github.com/tinyhat-ai/tinyhat/compare/v0.1.8...v0.2.0) (2026-05-27)


### Features

* **plugin:** Reset as OpenClaw platform package ([#99](https://github.com/tinyhat-ai/tinyhat/issues/99)) ([1340ccb](https://github.com/tinyhat-ai/tinyhat/commit/1340ccb655954ee7056ab5f6897be755875fa6ea))
* **skills:** Add authoring standard ([#102](https://github.com/tinyhat-ai/tinyhat/issues/102)) ([19a9294](https://github.com/tinyhat-ai/tinyhat/commit/19a92945e63b647384e98153217e6ddd08dda77c))
* **skills:** Add default capability router ([#103](https://github.com/tinyhat-ai/tinyhat/issues/103)) ([f1878bc](https://github.com/tinyhat-ai/tinyhat/commit/f1878bceee5118d6c824472777ee63426bb691d2))


### Bug Fixes

* **plugin:** Keep Mini App URLs transport-only ([#104](https://github.com/tinyhat-ai/tinyhat/issues/104)) ([933588a](https://github.com/tinyhat-ai/tinyhat/commit/933588a30fefd6af4b216d8eec5f51c573279315))

## [0.1.8](https://github.com/tinyhat-ai/tinyhat/compare/v0.1.7...v0.1.8) (2026-04-23)


### Features

* **skills:** Add review-changelog and wire into release flow ([#70](https://github.com/tinyhat-ai/tinyhat/issues/70)) ([6286ddf](https://github.com/tinyhat-ai/tinyhat/commit/6286ddfc229995fa75e3163f7cb6ab99b81c558d)), closes [#42](https://github.com/tinyhat-ai/tinyhat/issues/42)


### Bug Fixes

* **audit:** Direct agent to Bash heredoc for analysis JSON (closes [#39](https://github.com/tinyhat-ai/tinyhat/issues/39)) ([#75](https://github.com/tinyhat-ai/tinyhat/issues/75)) ([55b461a](https://github.com/tinyhat-ai/tinyhat/commit/55b461af95b855a31462f0e65a272d1f21e5515b))
* **audit:** Heads-up note when regenerating a same-day report (closes [#37](https://github.com/tinyhat-ai/tinyhat/issues/37)) ([#69](https://github.com/tinyhat-ai/tinyhat/issues/69)) ([26719f0](https://github.com/tinyhat-ai/tinyhat/commit/26719f0897fb3b2eecf4b3c644453febb57aa1a1))
* **audit:** Unbreak skill's load-time block + drop env-var prefix (closes [#63](https://github.com/tinyhat-ai/tinyhat/issues/63)) ([#67](https://github.com/tinyhat-ai/tinyhat/issues/67)) ([17b12cc](https://github.com/tinyhat-ai/tinyhat/commit/17b12cce57357bd2bfe57cd39df53137f97a2ec2))
* **release:** Bump plugin.json version with every release (closes [#64](https://github.com/tinyhat-ai/tinyhat/issues/64)) ([#65](https://github.com/tinyhat-ai/tinyhat/issues/65)) ([4ec820a](https://github.com/tinyhat-ai/tinyhat/commit/4ec820a2b4d130dfa880ae1699cd3e81f4e2a540))
* **report:** Archived reports link back to archive index correctly ([#68](https://github.com/tinyhat-ai/tinyhat/issues/68)) ([512de9d](https://github.com/tinyhat-ai/tinyhat/commit/512de9d88624dbfb583512c1b316fc5226209aed)), closes [#14](https://github.com/tinyhat-ai/tinyhat/issues/14)
* **report:** Hero doughnut arcs now match their integer labels (closes [#71](https://github.com/tinyhat-ai/tinyhat/issues/71)) ([#76](https://github.com/tinyhat-ai/tinyhat/issues/76)) ([54addf9](https://github.com/tinyhat-ai/tinyhat/commit/54addf9461c71d0f576aa0d21bb95fe86c538282))
* **snapshot:** Split gather output into compact + detail (closes [#38](https://github.com/tinyhat-ai/tinyhat/issues/38)) ([#72](https://github.com/tinyhat-ai/tinyhat/issues/72)) ([f015c72](https://github.com/tinyhat-ai/tinyhat/commit/f015c72e340e0057dbf1e7ce3b8cc2947ba2df15))

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
