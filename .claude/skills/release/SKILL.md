---
name: release
description: Use when cutting a Tinyhat release — reviewing the release-please PR, merging it, verifying the tag + GitHub release, smoke-testing the published plugin, or rolling back a bad release. Covers the automatic release-please flow, when to go off-script with a manual release, and the pre-1.0 versioning policy (bump-minor-pre-major). Invoke whenever you're about to land or review a release.
---

# release — cutting a Tinyhat release

Tinyhat uses [release-please](https://github.com/googleapis/release-please)
to automate the version bump, CHANGELOG entry, git tag, and GitHub
release. The normal path is: you merge a change to `main`, a release-
please PR appears, you review and merge it, the tag + release are
created automatically. Manual intervention is rare but documented
below.

## Versioning policy (pre-1.0)

Tinyhat is pre-alpha, so we stay in `0.x.y`:

- `feat:` commits bump **minor** (`0.1.0` → `0.2.0`).
- `fix:` commits bump **patch** (`0.1.0` → `0.1.1`).
- Breaking changes stay in minor bumps until we explicitly decide to
  ship `1.0.0`. Mark them with `!` in the commit type so they appear
  in the CHANGELOG's breaking-change section.

Release-please is already configured to honor this via
`.release-please-config.json` (`bump-minor-pre-major: true`,
`bump-patch-for-minor-pre-major: true`). Don't change that without
discussing first — it's the whole reason we reset from the accidental
v1.0.0.

Do NOT ship `1.0.0` until there's an explicit decision. At that
point:

1. Open a PR that sets `"bump-minor-pre-major": false` in
   `.release-please-config.json`.
2. Add `Release-As: 1.0.0` to a commit footer, or tell release-please
   the jump manually via a manifest edit.
3. Announce it separately.

## Normal flow (release-please-driven)

### 1. Confirm a release is warranted

Before touching anything, sanity-check:

```bash
gh pr list --repo tinyhat-ai/tinyhat --state open --label autorelease:pending
git log origin/main --oneline -20
```

You want at least one `feat:` or `fix:` in the window since the last
tag, and no in-flight blocker bug in the `bug` label.

### 2. Review the release-please PR

Every push to `main` re-runs release-please. It keeps a single open
PR titled `chore(main): release <version>` (label
`autorelease:pending`). When you're ready to cut:

```bash
gh pr view <N> --repo tinyhat-ai/tinyhat
```

Check:

- **Version bump is what you expect.** `feat:` → minor, `fix:` →
  patch. If release-please suggests a major bump but we're pre-1.0,
  something's misconfigured — stop and fix
  `.release-please-config.json`.
- **CHANGELOG entry reads well.** Release-please pulls commit
  subjects verbatim. If a subject is cryptic, amend it by editing
  `CHANGELOG.md` *in the release PR itself* — release-please won't
  overwrite manual edits.
- **`version.txt`, `.release-please-manifest.json`, and
  `.claude-plugin/plugin.json` all move to the new version.** All
  three get touched by the bot — `plugin.json` is wired in via
  `extra-files` in `.release-please-config.json` so the installed
  plugin label tracks the tag.
- **No unrelated file changes.** The only touched files should be
  `CHANGELOG.md`, `version.txt`, `.release-please-manifest.json`,
  `.claude-plugin/plugin.json`.

### 3. Merge the release PR (squash)

Squash-merge from the GitHub UI. Linear history is required.

On merge, release-please runs the release step:

- Creates an annotated tag `v<version>`.
- Publishes a GitHub release with the CHANGELOG slice as the body.
- Closes the autorelease PR and opens the next one (still titled
  `chore(main): release <next>` but empty until the next `feat:`/
  `fix:` lands).

### 4. Verify the release landed

```bash
# Tag exists and is annotated:
git fetch origin --tags && git show v<version> --stat | head

# GitHub release is public:
gh release view v<version> --repo tinyhat-ai/tinyhat

# Release workflow ran to success:
gh run list --repo tinyhat-ai/tinyhat --workflow Release --limit 3
```

If any step shows an error, jump to **Rollback** below.

### 5. Smoke-test the published plugin

In a clean Claude Code session:

```text
/plugin marketplace update tinyloop
/plugin install tinyhat@tinyloop
/reload-plugins
/tinyhat:audit
```

If the marketplace isn't already added (first smoke test on a new
machine), add it first: `/plugin marketplace add tinyhat-ai/tinyhat`.

Watch for:

- The four skills (`audit`, `open`, `history`, `routine`)
  register under the `tinyhat:` namespace.
- `gather_snapshot.py` and `render_report.py` run without import
  errors.
- The HTML report opens.

If a smoke test fails, **yank the release** (below) and file an
issue with what broke.

## Manual release (off-script)

Release-please handles 95% of cases. Use a manual release only when:

- You need to cut a patch immediately and can't wait for a
  release-please cycle (typically hours, not minutes).
- Release-please is stuck or misbehaving and you need to unstick it.

Steps:

1. Open a new branch: `chore/release-<version>`.
2. Bump `version.txt` and `.release-please-manifest.json` to the new
   version.
3. Prepend a CHANGELOG entry by hand (copy the release-please format:
   `## <version> (YYYY-MM-DD)` then `### Features` / `### Bug Fixes`
   sections with bullet links to the commits).
4. Commit with `chore: release <version>` as the subject, signed
   under your bot identity per the `commit` skill.
5. Open a PR, get it reviewed, squash-merge.
6. Tag it locally and push: `git tag -a v<version> -m "v<version>" &&
   git push origin v<version>`.
7. Create the GitHub release:
   `gh release create v<version> --repo tinyhat-ai/tinyhat --notes-file
   <(awk '/^## /{if(found)exit; found=1}found' CHANGELOG.md | tail -n +2)`.
8. Smoke-test per the Normal-flow step 5.

## Rollback (a release is broken)

A bad release that's been out for minutes: yank it.

```bash
# Delete the GitHub release (keeps the tag briefly):
gh release delete v<version> --repo tinyhat-ai/tinyhat --yes

# Delete the tag (remote and local):
git push origin :refs/tags/v<version>
git tag -d v<version>

# Walk release-please back: open a PR that sets the manifest back to
# the previous version. Release-please picks up the reset on next push.
```

Announce the rollback in whatever channel you use for releases (PR
comment, Slack, etc.). Then file a fix PR, get it merged, and let
release-please produce a new version number — don't try to re-use
the yanked tag.

A release that's been out **longer than a few minutes** and may
already be installed on users' machines: don't rollback, ship a
forward fix at the next patch number.

## Non-negotiables

- **Never publish from a branch other than `main`.** All releases are
  cut from `main` only.
- **Never re-use a yanked version number.** Cut a fresh patch.
- **Never skip the release-please PR.** If you're tempted to
  hand-tag `v<next>` on `main`, stop and use the manual-release flow
  instead so the CHANGELOG stays in sync.
- **Never bump to `1.0.0`** without an explicit policy change and a
  PR that flips `bump-minor-pre-major`. See the policy section above.
