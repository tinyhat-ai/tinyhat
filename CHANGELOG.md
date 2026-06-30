# Changelog

All notable changes to the Tinyhat plugin are documented here.

## Unreleased

### Changed

- Add `tinyhat_codex_auth` so agents can send the ChatGPT device-code
  prerequisite reminder and start the installed Codex auth flow directly.
- Require the agent to ask the user to enable ChatGPT Settings > Security
  > "Enable device code authorization for Codex" and confirm before
  starting the Codex auth helper.
- Use Hermes `clarify` for the one-tap confirmation, so Telegram renders
  the button under the prompt message instead of by the keyboard.
- Teach the private secret skill and tool to use meaningful env-style names
  such as `EXA_API_KEY` instead of generic placeholders like
  `TINYHAT_SECRET`.
- Add a repo-local Tinyhat plugin skill-authoring skill and expand the
  public skill standard for future plugin capabilities.
- Bump the fresh Hermes plugin package to `0.20.3` so managed Computers can
  verify the Tinyhat plugin update flow from `0.20.2`.
- Start the v0.20 Tinyhat plugin branch as a fresh Hermes-only package.
- Remove the legacy plugin surface from this branch.
- Add the first packaged skill, `tinyhat-tell-joke`, as an end-to-end
  plugin wiring proof.
- Make the first proof tool tolerate Hermes dispatcher metadata such as
  `task_id`, so it works from the first live agent interaction.
- Add `tinyhat-plugin-version` and `tinyhat_plugin_version` so a live
  Hermes agent can report the plugin version it is actually running.
- Document `channels/lts` and `channels/latest` as the install channels
  used by Tinyhat-managed Hermes Computers.
