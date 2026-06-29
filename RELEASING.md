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

During the v0.20 development window, both channels may point at the
reviewed `codex/v0.20-hermes-plugin` branch so Hermes Computers can
install this fresh plugin shape before the branch replaces `main`.

After the first final v0.20 release, channels should point at immutable
release tags unless the maintainer explicitly chooses a temporary test
window.

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

```bash
git ls-remote --heads origin channels/lts channels/latest
gh release list --repo tinyhat-ai/tinyhat --limit 10
```
