# Changelog

All notable changes to the Tinyhat plugin are documented here.

## Unreleased

### Changed

- Start the v0.20 Tinyhat plugin branch as a fresh Hermes-only package.
- Remove the legacy plugin surface from this branch.
- Add the first packaged skill, `tinyhat-tell-joke`, as an end-to-end
  plugin wiring proof.
- Make the first proof tool tolerate Hermes dispatcher metadata such as
  `task_id`, so it works from the first live agent interaction.
- Document `channels/lts` and `channels/latest` as the install channels
  used by Tinyhat-managed Hermes Computers.
