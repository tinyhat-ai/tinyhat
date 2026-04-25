---
name: review-pr
description: Use when asked to review a pull request, review a diff, inspect requested changes, or do a pre-landing review on tinyhat. Keeps the agent in review mode (find concrete bugs, regressions, missing tests, merge risks) instead of drifting into summaries, style commentary, or implementation. Covers GitHub PR review with `gh`, local uncommitted-diff review, the severity ladder, and the report shape (findings first, file:line references). Invoke instead of reading a diff and commenting freehand.
---

# review-pr — review a PR or diff in tinyhat's preferred style

Review mode is **not** implementation mode. Don't fix the PR unless
the maintainer explicitly asks for fixes — your job is to report
defects, risks, and gaps with enough specificity that the author can
act on them.

If you find yourself opening an editor, you've drifted out of the
skill. Stop and write up findings instead.

## 1. Resolve the surface

Two surfaces, two paths.

### A GitHub PR

Get the number `$N` from the user (or `gh pr list`). Pull metadata,
the diff, and the stated intent:

```bash
gh pr view $N --repo tinyhat-ai/tinyhat \
  --json number,title,baseRefName,headRefName,author,isDraft,mergeable

gh pr diff $N --repo tinyhat-ai/tinyhat

gh pr view $N --repo tinyhat-ai/tinyhat --json files \
  --jq '.files[] | "\(.additions)+ \(.deletions)- \(.path)"'

gh pr view $N --repo tinyhat-ai/tinyhat \
  --json title,body,closingIssuesReferences --comments
```

The PR body and the issue it closes carry the *stated intent* — read
both before judging the diff.

If the diff is large or context-heavy, `gh pr checkout $N` so you
can read nearby files. Don't review off `gh pr diff` alone when
context matters — single-file diff context is usually too narrow.

### A local uncommitted diff

```bash
git diff                          # unstaged
git diff --staged                 # staged
git diff origin/main...HEAD       # whole branch vs main
git status                        # untracked files
```

Always scan untracked files — a new file that should have been added
but wasn't is a real finding.

## 2. Read past the diff when context is missing

A diff alone isn't enough when a function's caller is outside the
changed lines, a fixture changed and you don't know what depends on
it, or a type widened and you don't know who reads it.

Open the file at the change site and search for callers:
`grep -rn '<symbol>' .`. Cheap and usually decisive.

## 3. Severity ladder

| Tier | What | Examples |
|---|---|---|
| **Blocker** | Wrong result, data loss, security regression, broken golden-path workflow, AGENTS.md non-negotiable violated | Off-by-one drops the last batch; unsigned commit slipped in |
| **Important** | Real bug on a non-golden path; missing test for a risky path | Error path drops the original cause; new branch added with no test |
| **Minor** | Likely-correct but worth a second look | Unclear name that hides a unit; comment contradicts code |
| **Question** | Not enough context to call it a defect | "Is this list expected to be empty here?" |
| **Nit** | Cosmetic. Optional. Use sparingly | Trailing whitespace, ordering |

Always tier. A finding without a tier reads as opinion.

## 4. Checklist

Walk this once before writing up:

- **Correctness:** does the changed behavior match the PR/issue intent?
  Run the golden path mentally; pick one edge case.
- **Tests:** every risky branch has coverage, or a stated reason it
  doesn't. New behavior without a new test is a finding.
- **Boundaries:** no unrelated refactors, generated churn, secrets,
  or local-only files (`.claude/worktrees/`, `CLAUDE.local.md*`,
  `__pycache__/`). One concern per diff.
- **Agent/process policy** (see [`AGENTS.md`](../../../AGENTS.md)):
  no maintainer-private content in committed files, no direct push
  to `main`, no agent self-merge, commit signed under the right bot
  identity.
- **User-facing impact:** docs, CLI output, error messages, and
  `SKILL.md` frontmatter stay coherent with what the code now does.
- **Integration risk:** CI still covers this; release config
  (`release-please-config.json`, `version.txt`,
  `.claude-plugin/plugin.json`) and skill-discovery metadata still
  packageable.

## 5. Report shape — findings first

```markdown
## Findings

### Blocker — <file>:<lines>
<one paragraph: what breaks, at which input, and why>
**Suggestion:** <one-line fix>

### Important — <file>:<lines>
…

### Question — <file>:<lines>
<single sentence grounded in the code>

## Summary
<two sentences max — what the PR does, your recommendation:
"approve", "approve with nits", "request changes", or "needs more
info before approval">
```

Findings first. Summary short and last. Don't restate the PR's
stated intent — the author already knows it.

When there are no findings, write one line and stop:

> No findings. Diff matches the issue (#80); tests cover the changed
> branches. Approve.

Don't pad a no-finding review with summaries.

## 6. Defect vs question

A finding is a *defect* when you can name what breaks and at which
input. If you can't, demote it to a *question*. Vague unease in the
findings list wastes the author's turn.

Good finding (defect):

> **Blocker — `gather_snapshot.py:142`**
> When `transcripts_dir` is empty, the loop returns `None` instead
> of `[]`, and `render_report.py:88` then calls `len(snapshot)` and
> crashes. Add `return []` on the empty branch.

Non-finding question:

> **Question — `routine.py:33`**
> Is the 24-hour cooldown intentional even when the previous run
> errored? Arguments either way — confirming.

Clean no-findings response:

> No findings. Diff matches issue #80, new branch in `pr_review.py`
> is covered by `test_pr_review.py:15`, no unrelated files moved.
> Approve.

A worked end-to-end transcript on a fictional PR lives in
[`example.md`](./example.md) — read it once to anchor on the shape.

## 7. Posting back

- **Maintainer wants the report in chat**: print it. Done.
- **Maintainer wants it on GitHub**: post the report as the PR
  review body, not as inline-line clutter:

  ```bash
  gh pr review $N --repo tinyhat-ai/tinyhat \
    --comment --body-file <path-to-report.md>
  ```

  Per-line comments only when the maintainer asked for them.

Never `gh pr review --approve` or `--request-changes` from a bot.
Approval is the maintainer / `CODEOWNERS` call.

## 8. Non-negotiables

- **Don't fix the PR.** Review only. If the maintainer explicitly
  asks "now fix it," that's a separate operation — start a fresh
  branch and use the [`commit`](../commit/SKILL.md) and
  [`open-pr`](../open-pr/SKILL.md) skills.
- **Don't approve or request changes from a bot identity.** Agents
  don't self-merge and don't formally block other agents' work.
- **Don't surface internal context** (`CLAUDE.local.md` or
  maintainer-private docs) in a public review.
- **Always tier.** A finding without a severity is an opinion.
- **Findings first, summary last, file:line on every finding.**
