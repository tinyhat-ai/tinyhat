---
name: define-tests
description: Pick the right verification set for changes in the public tinyhat-ai/tinyhat plugin repo.
---

# define-tests - tinyhat repo adapter

Parent alignment: when this repo is nested under Tinyloop, skim `../../../.agents/skills/define-tests/SKILL.md` for the current test-selection mindset.
Use this repo-specific matrix for actual commands.

## Matrix

| Change | Minimum checks |
| --- | --- |
| Dev skills / guidance only | `git diff --check`; `python3 scripts/check_dev_skills.py`; `bash .github/scripts/check_packaging.sh` |
| Packaged plugin skills or manifests | Above plus `python3 scripts/validate_openclaw_package.py`; `node --check src/index.js`; `node --test`; relevant manual OpenClaw smoke when available |
| Python scripts | Above plus `python3 -m compileall -q scripts`; `ruff check .`; `ruff format --check .` when ruff is available |
| Release files | Relevant checks above plus review `CHANGELOG.md` and release-please metadata |
| Roadmap docs | `git diff --check` and confirm every moved item references an issue |

Report exactly what ran.
If a tool such as `ruff` is not installed locally, say so and leave the CI check visible.
