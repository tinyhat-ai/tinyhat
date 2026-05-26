# Tinyhat Developer Skills

This directory is the canonical source for repo-local development skills.
`.claude/skills/*` entries are symlink adapters for Claude Code; Codex and other agents should read `.agents/skills/*/SKILL.md` directly.

When this repository is checked out under the Tinyloop monorepo at `platform_repos/plugins/tinyhat`, parent-aligned skills should first skim `../../../.agents/skills/<name>/SKILL.md` and then apply the repo-specific override in this public repository.
Use `TINYLOOP_PARENT_REPO=/path/to/tinyloop` from a standalone clone.

Run this after changing skills or adapters:

```bash
python3 scripts/check_dev_skills.py
```
