# Changelog

All notable changes to the Tinyhat plugin are documented here.

## Unreleased

### Changed

- Bump the Hermes plugin package to `0.21.3` and expose the existing safe,
  attested Computer platform-status endpoint as `tinyhat_get_platform_status`.
- Bump the Hermes plugin package to `0.21.2` so Google connection buttons can
  open the platform-authored Tinyhat preparation page before Google while
  retaining direct-Google URL compatibility during rollout.
- Bump the Hermes plugin package to `0.21.1` for Hermes-native Google
  Workspace operation guidance, binary-only `gws` integrity checks, and
  additive Calendar-event-write and combined Gmail/Calendar upgrades.
- Bump the Hermes plugin package to `0.21.0` for platform-owned Google
  Workspace OAuth, named Gmail-send permission upgrades, the bounded managed
  `gws` bridge, and the Computer-local two-stage revoke flow.
- Bump the fresh Hermes plugin package to `0.20.14` for the
  private-secret handoff survivor/queued-gateway-restart fix.
- Bump the fresh Hermes plugin package to `0.20.13`, add
  `tinyhat_skill_catalog` for plugin-qualified skill discovery, and add
  `tinyhat_plugin_update` so agents can check/apply stale installed plugin
  channels through runtime commands instead of ad hoc shell snippets.
- Stop restarting the Hermes gateway from the private-secret saver worker.
  After a secret is saved, the worker registers env passthrough, sends one
  honest Telegram notice, and claims the handoff with
  `outcome="installed_restart_pending"`; the Tinyhat platform queues the
  runtime's one-shot gateway restart and sends the final ready-or-failed
  confirmation after that command settles. Workers still prefer transient
  systemd survivor units (now defense in depth, not load-bearing) and fall
  back to a detached process when `systemd-run` is missing or fails.
  Deploy order: this plugin version requires a platform that queues the
  gateway restart when it receives the claim — deploy the platform change
  first, otherwise saved secrets do not reach a running gateway until a
  manual heal.
- Bump the fresh Hermes plugin package to `0.20.12` after tightening the
  agent-facing tool schemas and self-correcting error payloads.
- Register private-handoff secret names with the Tinyhat runtime's Hermes
  terminal env helper after saving. The runtime records the saved name and
  maintains Hermes local-terminal aliases so the secret is available to
  exec/shell subprocesses after gateway reload (requires the alias-capable
  runtime from tinyloophub/tinyhat--runtimes--hermes#68 or a later promoted
  runtime release; best effort on older runtimes).
- Add `tinyhat_codex_auth` so agents can send the ChatGPT device-code
  prerequisite reminder and start the installed Codex auth flow directly.
- Route natural-language Codex subscription requests to the screenshot
  prerequisite helper by default, so the user sees the ChatGPT Settings >
  Security visual guide and `/codex_auth` without duplicate text replies.
- Teach the private secret skill and tool to use meaningful env-style names
  such as `EXA_API_KEY` instead of generic placeholders like
  `TINYHAT_SECRET`.
- Restart the gateway after a private secret is saved, with a short Telegram
  notice first, so the runtime can load the env value before the next message.
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
