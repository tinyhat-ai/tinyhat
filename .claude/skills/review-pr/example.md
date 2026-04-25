# example.md — dry-run review transcript

Worked example for the [`review-pr`](./SKILL.md) skill on a fictional
PR. Read it once to anchor on the output shape; don't paste from it
as a template.

## Fictional setup

- **PR:** `#142` on `tinyhat-ai/tinyhat` — *"feat(audit): skip
  dormant skills older than 90 days"*.
- **Author:** an external contributor.
- **Base:** `main`. **Diff:** 2 files
  (`gather_snapshot.py` +18, -2; `audit_routine.md` +4, -1).
- **Untracked next to the diff:** `gather_snapshot.py.bak`.
- **Stated intent (PR body):** *"Audit shouldn't fail when a skill
  hasn't been used in 90+ days. Skip them silently."*

## Walkthrough

### 1. Resolve

```bash
gh pr view 142 --repo tinyhat-ai/tinyhat \
  --json baseRefName,headRefName,files,title,body
gh pr diff 142 --repo tinyhat-ai/tinyhat
gh pr view 142 --repo tinyhat-ai/tinyhat --json files \
  --jq '.files[] | "\(.additions)+ \(.deletions)- \(.path)"'
```

Two files in the PR; one stray `.bak` shows up via `gh pr view ... files`
(or `git status` after `gh pr checkout 142`). Backup files don't
belong in commits — flag.

### 2. Read past the diff

```bash
gh pr checkout 142
grep -rn 'gather_snapshot' .
```

Two callers: `render_report.py` and `test_gather_snapshot.py`. The
new branch in `gather_snapshot.py:94` is uncovered by any case in
the test file.

### 3. Tier and write up

```markdown
## Findings

### Blocker — `gather_snapshot.py.bak`
The PR includes an untracked backup file the author probably forgot
to delete. It will be committed if the maintainer squash-merges
without checking. Remove it before merge.
**Suggestion:** `git rm gather_snapshot.py.bak` and force-push.

### Important — `gather_snapshot.py:94`
The new "skip if older than 90 days" branch has no test. The existing
`test_gather_snapshot.py` covers the under-90-days path only, so a
regression that skips the wrong skills (or fails to skip) won't be
caught by CI.
**Suggestion:** add a fixture transcript dated 91 days ago and
assert it's omitted from the snapshot.

### Question — `audit_routine.md:14`
The doc says "skipped skills are listed in the report footer" but
the code change drops them silently. Is the doc the new spec, or is
it now out of date?

## Summary
Adds a 90-day cutoff for dormant skills in the audit snapshot.
Approve once the `.bak` file is removed and the new branch has a
test; doc/code mismatch needs the author's confirmation.
```

## Why this shape

- The Blocker comes first because it can land in `main` if missed.
- The Important finding is a real test gap, not a style nit.
- The Question doesn't claim a defect — the doc could be either the
  new source of truth or stale. Reviewer flags it; author decides.
- The Summary is two sentences. It does not restate stated intent.
  It does state a recommendation.
- File:line on every finding.
- No suggested patch in the review — only one-line fix hints. If
  the maintainer says "now fix it," the agent leaves review mode
  and runs the [`commit`](../commit/SKILL.md) skill on a fresh
  branch.
