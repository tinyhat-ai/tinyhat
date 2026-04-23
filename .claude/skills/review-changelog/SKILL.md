---
name: review-changelog
description: Use before merging a release-please PR on tinyhat to check that each CHANGELOG entry matches what actually shipped. Release-please cribs every bullet from the source PR's squashed-merge commit subject; if review replaced the mechanism that subject described, the bullet advertises an abandoned approach. This skill surfaces divergences and lands a rewrite on the release-please branch under the bot identity. Invoke from the `release` skill's pre-merge step, or standalone.
---

# review-changelog — check release-please bullets against what shipped

Release-please writes each `CHANGELOG.md` bullet from the source PR's
squashed-merge commit subject. If the PR landed with a subject that
described its *first-draft* mechanism, and review replaced that
mechanism, the bullet tells users about an approach that didn't ship.
This skill catches that before the release PR merges.

Scope is narrow: the single open release-please PR. Not a general
changelog linter.

## 1. Pick the open release PR

```bash
gh pr list --repo tinyhat-ai/tinyhat --state open \
  --label "autorelease:pending" \
  --json number,title,headRefName,url
```

There should be exactly one. Record the PR number (`$RP`) and head
branch (`$RBR`, typically `release-please--branches--main`). Zero
results means there's no release in flight — nothing to do.

## 2. Read the new CHANGELOG entries

```bash
gh pr diff $RP --repo tinyhat-ai/tinyhat -- CHANGELOG.md
```

Each `+` bullet is a candidate. Every release-please bullet links its
source PR as `(#NN)` at the end — pull those numbers out into a list.

## 3. For each source PR, compare subject to what shipped

For every `$N` in the list:

```bash
# Subject — what release-please is saying:
gh pr view $N --repo tinyhat-ai/tinyhat \
  --json title,body,mergeCommit --jq '{title, merge: .mergeCommit.oid}'

# Reality — what actually shipped:
gh pr diff $N --repo tinyhat-ai/tinyhat

# Review trail — watch for "replaced with", "superseded by",
# "switched to", "instead of", "ended up", "dropped":
gh pr view $N --repo tinyhat-ai/tinyhat --comments
```

Form a two-sentence summary in your head: *"Subject says X. Diff shows
Y."* If the mechanism verbs and object nouns in the subject still
appear in the diff, the bullet is accurate — move on. If they don't,
or the review trail contains a redesign phrase, flag it.

Judgment, not a keyword matcher. A word-level diff will flag cosmetic
rewordings; a strict matcher will miss semantic redesigns. Read both
versions and decide.

## 4. Decide with the maintainer

If nothing diverges, respond with a single line — *"CHANGELOG matches
shipping behavior, nothing to rewrite"* — and stop. Don't spend a
maintainer turn on a no-op.

Otherwise surface flagged entries as a table:

| Current bullet | What actually shipped | Proposed rewrite |
|---|---|---|
| *"Persist plugin root at load time (#41)"* | Text-substitute `${CLAUDE_SKILL_DIR}`, no file written | *"Substitute plugin root via `${CLAUDE_SKILL_DIR}` at skill load (#41)"* |

Ask the maintainer to approve, edit, or drop each proposed rewrite.
Don't proceed to step 5 without an explicit approval per entry.

## 5. Rewrite on the release branch

The release-please branch accepts manual edits; release-please won't
clobber them unless it regenerates from a new push to `main`. Check
out the branch, edit `CHANGELOG.md` inline, and commit under your bot
identity per the [`commit`](../commit/SKILL.md) skill:

```bash
git fetch origin $RBR
git checkout $RBR
# Edit CHANGELOG.md — keep the heading level, bullet form, and
# trailing (#NN) link exactly as release-please wrote them.
bot_git commit -m "chore(release): clarify changelog entry for #$N" \
  CHANGELOG.md
GIT_SSH_COMMAND="ssh -i $HOME/.ssh/<agent-key> -o IdentitiesOnly=yes" \
  git push origin $RBR
```

If the PR body also quotes the old subject (release-please mirrors the
CHANGELOG into the PR description), update it in the same pass:

```bash
gh pr view $RP --repo tinyhat-ai/tinyhat --json body --jq .body \
  > /tmp/pr-body.md
# Edit /tmp/pr-body.md to match the new CHANGELOG.
gh pr edit $RP --repo tinyhat-ai/tinyhat --body-file /tmp/pr-body.md
```

## 6. Re-check before handing back

```bash
# Confirm the label is still there (release-please didn't regenerate):
gh pr view $RP --repo tinyhat-ai/tinyhat \
  --json labels --jq '.labels[].name'

# Confirm the signed bot commit landed:
gh pr view $RP --repo tinyhat-ai/tinyhat --json commits \
  --jq '.commits[-1] | {oid:.oid, msg:.messageHeadline, author:.authors[0].login}'
```

If `main` advanced between your edit and now, release-please may have
regenerated the PR — re-run from step 2. Otherwise return to the
[`release`](../release/SKILL.md) skill and continue to "Merge the
release PR (squash)."

## 7. Non-negotiables

- Never rewrite the squashed-merge commit on `main`. Only
  `CHANGELOG.md` and the release PR body get touched.
- Never commit the rewrite without the `commit` skill's inline bot
  identity overrides.
- Never rewrite a CHANGELOG entry after the release PR has been
  merged — the tag is already cut. Ship a forward fix instead.
- Never flag an entry purely on a keyword match without reading the
  diff. Cosmetic subject rewordings are fine; mechanism drift is not.
