# Releasing

Tinyhat plugin releases are separate from Tinyhat runtime releases.

The runtime asks for a plugin channel. This repo decides what that channel
means.

## Version Shapes

- Final releases: `vX.Y.Z`
- Release candidates: `vX.Y.Z-rc.N`
- Development releases: `vX.Y.Z-dev.YYYYMMDDTHHMMSSZ[.suffix]`

GitHub release titles should match the tag exactly. Final releases are
not pre-releases. Release candidates and development releases are
pre-releases.

## Channels

| Branch | Meaning |
| --- | --- |
| `channels/lts` | Conservative default for managed Computers. |
| `channels/latest` | Newest promoted final branch/tag for faster adoption. |

During the v0.20 development window, reviewed changes merge into
`codex/v0.20-hermes-plugin`. Treat that as a staging branch, not permission to
move an install channel before required platform compatibility is deployed.

After the first final v0.20 release, channels should point at immutable
release tags unless the maintainer explicitly chooses a temporary test
window.

## Platform-Gated Promotion Sequence

Use this ordering when a plugin change depends on matching platform
enforcement or API behavior:

1. Merge the reviewed plugin change into `codex/v0.20-hermes-plugin`.
2. Pin that exact merged commit in the platform release. The platform's normal
   pin check may report it as staged for promotion; its strict release check
   must still reject it while `channels/lts` is older.
3. Merge and deploy the compatible platform change.
4. Publish the final plugin release from the exact pinned commit.
5. Promote `channels/latest` and `channels/lts` to that release only after the
   compatible platform deployment is confirmed healthy.
6. Re-run the platform's strict pin check and confirm the release, channel, and
   pinned commit are exact.

Do not use this sequence for an open PR head. The pinned commit must already be
contained in the trusted staging branch, and a squash/rebase that replaces the
commit invalidates the old pin.

## Promote A Branch During v0.20 Build-Out

```bash
BRANCH=codex/v0.20-hermes-plugin
git fetch origin "$BRANCH"
git checkout -B channels/lts "origin/$BRANCH"
git push origin channels/lts --force-with-lease
git checkout -B channels/latest "origin/$BRANCH"
git push origin channels/latest --force-with-lease
```

## Promote A Final Release

```bash
TAG=vX.Y.Z
git fetch origin --tags
gh release edit "$TAG" \
  --repo tinyhat-ai/tinyhat \
  --latest \
  --prerelease=false \
  --draft=false
git checkout -B channels/latest "$TAG"
git push origin channels/latest --force-with-lease
git checkout -B channels/lts "$TAG"
git push origin channels/lts --force-with-lease
```

## Verify

Before changing `PINNED_GWS_VERSION`, audit that release's local roots, API
aliases, synthetic helpers, and global flags in `googleworkspace/cli` source.
Update `AUDITED_ALLOWED_ROOT_COMMANDS_BY_GWS_VERSION` and its exact-set test in
the same PR. Keep public `schema` plus ordinary Discovery API aliases; auth,
setup, synthetic workflow, skill-generation, export, and server commands must
remain blocked. An unaudited version intentionally fails closed for every bridge
command.

```bash
git ls-remote --heads origin channels/lts channels/latest
gh release list --repo tinyhat-ai/tinyhat --limit 10
```
