---
name: review
description: Review PRs in the public tinyhat-ai/tinyhat repo using parent Tinyloop review quality rules with plugin-specific packaging and public-safety checks.
---

# review - tinyhat repo adapter

Parent alignment: when this repo is nested under Tinyloop, first read `../../../.agents/skills/review/SKILL.md` for review depth, posted-review expectations, and finding format.
Apply the plugin-specific risk checklist below.

## Plugin Checklist

- Dev-only skills and scripts stay out of packaged plugin surfaces under `skills/`.
- `.agents/skills` remains the canonical dev-skill source; `.claude/skills` entries are symlinks only.
- Public docs and skills do not expose private Drive paths, secrets, internal URLs, or local-only hostnames.
- Packaged `SKILL.md` files stay compact and focused.
- `openclaw.plugin.json`, `package.json`, and `src/index.js` agree on the tool surface.
- Release-please metadata and CHANGELOG entries match the shipped behavior.

## Evidence

Prefer concrete commands:

```bash
git diff --check
python3 scripts/check_dev_skills.py
bash .github/scripts/check_packaging.sh
python3 scripts/validate_openclaw_package.py
python3 -m compileall -q scripts
node --check src/index.js
```

Post GitHub reviews under the Codex bot when acting as Codex, and end with `— posted by Codex`.
