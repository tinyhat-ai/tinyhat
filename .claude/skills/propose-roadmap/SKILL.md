---
name: propose-roadmap
description: Use when a contributor (human or agent) wants to propose a change to the Tinyhat roadmap — moving an item between now/next/later/considering, adding a new candidate, or flagging something for rejection. Covers the required PR format and what makes a proposal reviewable. Invoke instead of editing roadmap files directly.
---

# propose-roadmap — how to open a roadmap-change proposal

The roadmap lives in `roadmap/` (six markdown files).
It is versioned in git, so every priority change is reviewable and diffable.
This skill walks you through the right PR format so your proposal is unambiguous.

## 1. Prerequisites

A roadmap change PR must reference at least one issue.
If the thing you want to move doesn't have an issue yet, open one first:

- Bug or regression → use the [bug report template](../../.github/ISSUE_TEMPLATE/bug_report.yml)
- Feature or improvement → use the [feature request template](../../.github/ISSUE_TEMPLATE/feature_request.yml)
- Or use the `/file-issue` skill (when available) from inside Claude Code.

## 2. What kind of change is this?

Pick one:

| Change | Target file |
|---|---|
| Promote an item into active work | Move entry to `roadmap/now.md` |
| Queue an item for the next cycle | Move entry to `roadmap/next.md` |
| Park a big bet | Move entry to `roadmap/later.md` |
| Surface an idea for evaluation | Add to `roadmap/considering.md` |
| Explicitly decline something | Add to `roadmap/rejected.md` with a reason |

One move per PR. If you want to move three things, open three PRs.
Reviewers can approve them in any order or decline some and merge others.

## 3. The entry format

Every item in `now.md`, `next.md`, and `later.md` uses this shape:

```markdown
## <Short title — match the issue title if possible>
- **Tracks:** #<issue number>
- **Why it's here:** <one or two sentences on the user pain or strategic value>
- **Blocks:** #<issue> or — if nothing
- **Blocked by:** #<issue> or — if nothing
- **Proposed outcome:** <what done looks like — one sentence>
```

For `considering.md`:

```markdown
## <Short title>
- **Tracks:** #<issue number>
- **What's being evaluated:** <what signal or decision is missing before committing>
```

For `rejected.md`:

```markdown
## <Short title>
- **Tracks:** #<issue number> (or "no issue — proposed via roadmap PR")
- **Why not:** <the constraint, principle, or tradeoff that makes this a no for now>
```

## 4. Branch and PR

Branch name: `<your-handle-or-bot-name>/roadmap-<short-topic>`

```bash
git checkout -b <branch>
# edit the relevant roadmap/*.md file(s)
git add roadmap/
```

Then commit (see the [`commit`](../commit/SKILL.md) skill for signing + identity),
and open a PR:

- **Title:** `roadmap: <one-line ask>` — e.g. `roadmap: move #19 from later to next`
- **Body:** include the user pain, the issue link, and what you expect the merged
  state to look like. Keep it under a screen.
- **Base:** `main`

```bash
gh pr create --base main \
  --title "roadmap: <one-line ask>" \
  --body "$(cat <<'EOF'
## What this moves

<!-- State the item and the source → destination files -->

## Why now

<!-- One paragraph: the user pain or new signal that justifies the move -->

## Issue(s)

Closes / relates to #<number>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

## 5. What happens after

- The maintainer reviews the priority argument, not just the formatting.
  A well-written "why now" is the proposal.
- If accepted: PR is squash-merged, item moves in the roadmap.
- If declined: maintainer adds the item to `rejected.md` with a short reason
  and closes the PR, referencing the rejection entry.
- If the issue doesn't exist yet: PR is sent back with a request to open the
  issue first.

## 6. Non-negotiables

- One move per PR.
- Every move links to at least one open issue.
- Don't edit `now.md` to queue more than 3 items — if it's full, promote one to
  done (link to the merged PR) or start a discussion on deferral first.
- Roadmap PRs don't need CI to pass (there's no code), but they must pass
  `ruff` if any Python was accidentally touched.
