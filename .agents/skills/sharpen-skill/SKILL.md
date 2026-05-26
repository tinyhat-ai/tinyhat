---
name: sharpen-skill
description: Edit or add development skills in the public tinyhat-ai/tinyhat repo while keeping them aligned with Tinyloop parent skill patterns.
---

# sharpen-skill - tinyhat repo adapter

Parent alignment: when this repo is nested under Tinyloop, first read `../../../.agents/skills/sharpen-skill/SKILL.md` for the current skill-editing workflow.
Then keep this repo's public dev skills small and adapter-shaped.

## Rules

- Canonical dev skills live in `.agents/skills/<name>/SKILL.md`.
- `.claude/skills/<name>` must be a symlink to `../../.agents/skills/<name>`.
- Product/user-facing plugin skills live under `skills/`; do not mix them with repo-local dev skills.
- Prefer adapter skills that cite the parent Tinyloop skill and list only public-repo-specific overrides.
- Do not paste large parent skill bodies into this public repo.
- Keep private Tinyloop docs, local paths, and secrets out of skill text.

## Validate

```bash
python3 scripts/check_dev_skills.py
bash .github/scripts/check_packaging.sh
git diff --check
```
