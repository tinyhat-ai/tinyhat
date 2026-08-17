# Releasing the Tinyhat plugin

Tinyhat plugin releases are separate from Tinyloop and Hermes runtime
releases. Immutable tags answer "what exact plugin code is this?" Channel
branches answer "what final plugin should a managed Computer install?"

## Release shapes

- Final releases: `vX.Y.Z`
- Release candidates: `vX.Y.Z-rc.N`
- Development releases: `vX.Y.Z-dev.YYYYMMDDTHHMMSSZ[.suffix]`

The GitHub release title must equal the tag. Final releases are not
pre-releases. Candidates and development releases are pre-releases and never
Latest. Published tags are immutable.

## Version bump checklist

Update every live version surface in one change. `VERSION` is the concise
repository release version. The version shown by a running Agent comes from
`hermes.plugin.json`.

| File | What the version controls |
| --- | --- |
| `VERSION` | Repository release and channel version. |
| `package.json` | Canonical plugin package version used by release automation and validation. |
| `hermes.plugin.json` | Loaded adapter version reported by `tinyhat_plugin_version`. |
| `plugin.yaml` | Hermes plugin-loader manifest version. |
| `pyproject.toml` | Python package metadata version. |
| `.release-please-manifest.json` | Release Please state for the repository root. |
| `test/test_hermes_adapter.py` | Live-version expectations and version-bearing fixtures. |

Also add a dated version section and user-visible summary to `CHANGELOG.md`.
When a matching platform deployment is required, document that dependency in
the release notes and verify the platform before channel promotion.

Before committing:

```bash
PLUGIN_OLD_VERSION='<current-version>'
PLUGIN_NEW_VERSION='<next-version>'
rg -n --hidden --glob '!.git/**' \
  "$PLUGIN_OLD_VERSION|$PLUGIN_NEW_VERSION"
python3 scripts/validate_framework_package.py
python3 -m unittest discover -s test -p "*.py"
python3 -m compileall -q .
```

Review every search result. Historical changelog entries keep their original
versions. `scripts/validate_framework_package.py` must prove all live version
surfaces agree.

The Release Please workflow is manually dispatched. Its generated PR is only
a starting point: complete every version surface in the table before merging.

## Publish a final release

Publish only from a clean, reviewed commit contained in `main`:

```bash
VERSION="$(tr -d '[:space:]' < VERSION)"
TAG="v${VERSION}"
SHA="$(git rev-parse HEAD)"

git fetch origin main --tags
git merge-base --is-ancestor "$SHA" origin/main
python3 scripts/validate_framework_package.py
python3 -m unittest discover -s test -p "*.py"
python3 -m compileall -q .

git tag -s "$TAG" "$SHA" -m "$TAG"
git push origin "$TAG"
gh release create "$TAG" \
  --repo tinyhat-ai/tinyhat \
  --title "$TAG" \
  --latest \
  --verify-tag \
  --notes-file /tmp/tinyhat-plugin-release-notes.md
```

For a candidate or development release, use its exact tag shape, mark the
GitHub release Pre-release, and keep Latest off. Never move a default channel
to a candidate or development tag.

## Channels

| Branch | Meaning |
| --- | --- |
| `channels/latest` | Newest promoted final release. |
| `channels/lts` | Conservative default for managed Computers. |

The channel branches are protected moving refs. Update them through the GitHub
refs API to the final release commit rather than pushing directly:

```bash
TAG=vX.Y.Z
SHA="$(git rev-list -n 1 "$TAG")"

gh api --method PATCH \
  repos/tinyhat-ai/tinyhat/git/refs/heads/channels/latest \
  -f sha="$SHA" -F force=true
gh api --method PATCH \
  repos/tinyhat-ai/tinyhat/git/refs/heads/channels/lts \
  -f sha="$SHA" -F force=true
```

For platform-dependent changes, use this order:

1. Merge the reviewed plugin change to `main`.
2. Deploy and verify the compatible Tinyloop platform.
3. Publish the final plugin tag and GitHub release from the exact reviewed
   `main` commit.
4. Move `channels/latest` and, when appropriate, `channels/lts` to that exact
   final release commit.
5. Re-read the release markers, both remote channel SHAs, and
   `hermes.plugin.json` from each channel.

## Verify

```bash
TAG=vX.Y.Z
gh release view "$TAG" \
  --repo tinyhat-ai/tinyhat \
  --json tagName,name,isPrerelease,isDraft,isLatest,targetCommitish
git ls-remote --heads origin channels/lts channels/latest
```

Expected for a promoted final release:

- `tagName` and release `name` both equal `TAG`.
- `isDraft` and `isPrerelease` are false.
- `isLatest` is true.
- Both channel refs resolve to the commit identified by `TAG`.
- `VERSION`, `hermes.plugin.json`, and all other live surfaces report the same
  final version on both channels.

Before changing `PINNED_GWS_VERSION`, also audit that release's local roots,
API aliases, synthetic helpers, and global flags in `googleworkspace/cli`.
Update `AUDITED_ALLOWED_ROOT_COMMANDS_BY_GWS_VERSION` and its exact-set test in
the same PR. An unaudited version intentionally fails closed for every bridge
command.
