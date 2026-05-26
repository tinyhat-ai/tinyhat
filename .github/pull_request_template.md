## Summary

<!-- What changed and why. One or two sentences. -->

## Linked Issue

Closes #

## Type Of Change

- [ ] `feat` - new feature
- [ ] `fix` - bug fix
- [ ] `docs` - documentation only
- [ ] `refactor` - no behavior change
- [ ] `test` - tests only
- [ ] `chore` / `ci` / `build` - tooling
- [ ] Breaking change

## Testing Performed

- [ ] `git diff --check`
- [ ] `python3 scripts/check_dev_skills.py`
- [ ] `bash .github/scripts/check_packaging.sh`
- [ ] `python3 scripts/validate_openclaw_package.py`
- [ ] `python3 -m compileall -q scripts`
- [ ] `node --check src/index.js`
- [ ] `node --test`
- [ ] `ruff check .` and `ruff format --check .`
- [ ] Manual OpenClaw plugin smoke test, if applicable

## Screenshots Or Logs

<!-- For visible Telegram/OpenClaw behavior, paste redacted output or screenshots. -->

## Checklist

- [ ] PR title is a Conventional Commit.
- [ ] Linked to an issue or this PR is the canonical spec.
- [ ] Docs updated where behavior changed.
- [ ] Packaged skill changes follow `docs/skill-authoring.md`.
- [ ] CI is green.
- [ ] No tenant secrets, signed Mini App URLs, private backend URLs, local-only
      paths, or internal docs are included.
- [ ] I will not self-merge.

<details>
<summary>Agent checklist</summary>

- [ ] Commits follow the repo bot-identity/signing rules in `AGENTS.md`.
- [ ] Branch named with an agent or contributor prefix.

</details>
