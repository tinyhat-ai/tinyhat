# Tinyhat plugin versioning

This repository has two separate release concepts:

- **Immutable release tags** identify the exact plugin code.
- **Channel branches** identify which final release managed Computers install.

The plugin versions independently from Tinyloop and the Hermes runtime. Never
move a published SemVer tag. Move a channel branch only when promoting an
existing final release.

## Release lifecycle

| Phase | Tag shape | GitHub marker | Channel branch | Purpose |
| --- | --- | --- | --- | --- |
| Development | `vX.Y.Z-dev.YYYYMMDDTHHMMSSZ[.suffix]` | Pre-release, not Latest | none | Exact test build. |
| Candidate | `vX.Y.Z-rc.N` | Pre-release, not Latest | none | Reviewable release candidate. |
| Final | `vX.Y.Z` | Release; Latest when promoted | optional `channels/latest` | Stable immutable plugin version. |
| LTS | existing final `vX.Y.Z` | Release | `channels/lts` | Conservative managed-Computer default. |

## Source branches

`main` is the integration and release branch. The former
`codex/v0.20-hermes-plugin` staging branch was used while Hermes adoption was
incomplete; it is not a release authority after `v0.28.0`.

All normal changes reach `main` through reviewed pull requests. Release tags
must identify commits contained in `main`.

## Promotion rules

1. Publish development and candidate builds only by exact tag. They never move
   `channels/latest` or `channels/lts`.
2. Publish final tags from reviewed commits contained in `main`.
3. Move `channels/latest` only to the commit identified by a final release.
4. Move `channels/lts` only after that final release is suitable as the
   conservative default.
5. For platform-dependent features, deploy and verify the compatible Tinyloop
   platform before moving either channel.

See `RELEASING.md` for the complete version, release-marker, and remote
read-back checklist.
