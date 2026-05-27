---
name: release
description: Use when cutting a Tinyhat OpenClaw plugin release: reviewing a release-please PR, verifying version metadata, smoke-testing the published plugin package, or rolling back a bad release.
---

# release - tinyhat repo adapter

Parent alignment: when this repo is nested under Tinyloop at
`platform_repos/plugins/tinyhat`, skim
`../../../.agents/skills/release/SKILL.md` for current release
discipline.

## Version Policy

Tinyhat is pre-1.0. `feat:` commits bump minor, `fix:` commits bump
patch, and breaking changes stay in the 0.x line until the maintainer
explicitly chooses 1.0.

Release-please updates:

- `CHANGELOG.md`
- `.release-please-manifest.json`
- `package.json`
- `openclaw.plugin.json`
- `pyproject.toml`

No `version.txt` or `.claude-plugin` files exist in this package.

## Review A Release PR

1. Find the open release PR:

   ```bash
   gh pr list --repo tinyhat-ai/tinyhat --state open --label autorelease:pending
   ```

2. Verify the proposed version is right for the commits since the last
   tag.
3. Verify the only versioned package files are the files listed
   above.
4. Check that CHANGELOG entries describe shipped OpenClaw plugin
   behavior.
5. Run the standard package checks:

   ```bash
   git diff --check
   python3 scripts/check_dev_skills.py
   bash .github/scripts/check_packaging.sh
   python3 scripts/validate_openclaw_package.py
   python3 -m compileall -q scripts
   node --check src/index.js
   ```

## Smoke-Test A Published Release

In an OpenClaw development environment:

```bash
openclaw plugins install /path/to/tinyhat --force
```

Confirm OpenClaw loads plugin id `tinyhat`, extension `./src/index.js`,
and the packaged `skills/` directory. For a Tinyhat-managed runtime,
also confirm the platform pins the expected repo/ref and the Computer
can call status plus one Telegram-button capability.

## Non-Negotiables

- Never publish tenant secrets, signed URLs, private backend URLs, or
  internal deployment notes in release text.
- Never merge a release PR whose package version fields disagree.
- Never self-merge an agent-authored release PR.
