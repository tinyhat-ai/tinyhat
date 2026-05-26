---
name: codex
description: Codex conventions for the public tinyhat-ai/tinyhat repo. Use for GitHub writeback, PR comments/reviews, issue comments, and identity restoration.
---

# codex - tinyhat repo adapter

Parent alignment: when this repo is nested under Tinyloop, first read `../../../.agents/skills/codex/SKILL.md` for the current Codex writeback contract.
Apply the overrides below for `tinyhat-ai/tinyhat`.

## Rules

- Codex-authored GitHub comments and reviews use `tinyloop-farid-codex` when that account has access.
- Restore `gh` to `farid-tinyloop` after the write and verify with `gh auth status`.
- End every Codex-authored GitHub comment/review body with:

```text
— posted by Codex
```

- Use the target repo explicitly in commands:

```bash
gh pr view <n> --repo tinyhat-ai/tinyhat
gh issue view <n> --repo tinyhat-ai/tinyhat
```

## Public-Repo Boundary

Do not copy private Tinyloop monorepo details, Drive paths, secrets, local env values, or internal URLs into this public repo, PR bodies, issues, or comments.
