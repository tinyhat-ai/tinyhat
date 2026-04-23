## Summary

<!-- What changed and why. One or two sentences. -->

## Linked issue

Closes #

## Type of change

<!-- Check one or more. -->

- [ ] `feat` — new feature
- [ ] `fix` — bug fix
- [ ] `docs` — documentation only
- [ ] `refactor` — no behavior change
- [ ] `test` — tests only
- [ ] `chore` / `ci` / `build` — tooling
- [ ] Breaking change (requires `!` in the type or a `BREAKING CHANGE:` footer)

## Testing performed

<!-- Commands you ran, manual steps, what you verified. -->

- [ ] Ran `python3 scripts/gather_snapshot.py` successfully
- [ ] Ran `python3 scripts/render_report.py --open` successfully
- [ ] Exercised the plugin via `claude --plugin-dir "$(pwd)"`
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] Added / updated tests where applicable

## Screenshots (if UI)

<!-- For changes to report.html, the index page, or anything the user sees. -->

## Checklist

- [ ] PR title is a Conventional Commit (e.g. `feat(skills): …`, `fix: …`)
- [ ] Linked to an issue (`Closes #…`) or this PR is the canonical spec
- [ ] Tests added or updated (or this PR is docs/chore only)
- [ ] Docs updated where behavior changed
- [ ] CI is green
- [ ] No references to private maintainer resources (see [AGENTS.md](../AGENTS.md#local-override-files))
- [ ] I will not self-merge

---

<details>
<summary>Agent checklist (only if a bot opened this PR)</summary>

- [ ] Commits signed with the bot's SSH key and identity — see
      [`commit` skill](../.claude/skills/commit/SKILL.md).
- [ ] Branch named `<agent>/<short-topic>`.

</details>
