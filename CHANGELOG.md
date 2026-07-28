# Changelog

All notable changes to the Tinyhat plugin are documented here.

## Unreleased

### Changed

- Bump the Hermes plugin package to `0.21.13`; teach agents the funding model
  and make connecting the subscription an explicit onboarding step
  (relands the `0.21.10` funding work that missed the release channels). A new agent
  starts on Tinyhat's included platform credits — a small starter credit
  (about $10) so it works immediately — and the intended ongoing fund is the
  user's own ChatGPT / Codex subscription connected through `/codex_auth`.
  On the first conversation turn after setup or an in-place upgrade the
  injected context adds a one-time funding-note directive ahead of the
  context: a new user's onboarding reply presents connecting the
  ChatGPT / Codex subscription as one of its onboarding steps (a
  numbered or bulleted step when the reply lists steps, a standalone
  step line otherwise, never a footnote), a clearly returning user gets
  one brief line, and an already-connected subscription skips the note
  silently. The claim is recorded with a durable per-Computer marker so
  a later `/new` or `/reset` session does not re-arm it. The directive
  is a first-message `[System note]` coordinated with Hermes's own
  profile-build note, and the payload stays under Hermes's ~10k
  hook-context spill cap (directive first, whole tail bullets dropped
  when needed while bullets matched by the user's own first message —
  privacy, funding — always survive) so the note reaches the model
  inline; tool-owned native first
  replies (the Codex auth prerequisite photo, a Connect Google button) or an
  explicit connect request satisfy the step on their own. Agents check
  `tinyhat_codex_auth` `action=status` before claiming a subscription is not
  connected, never state a remaining credit balance they cannot see, and
  answer how-is-this-paid-for / is-this-free / credits-ran-out questions
  from the model. Funding routing is bounded: command frames are suppressed
  before any funding matching, then end-anchored question forms and
  bounded funding phrases, a funding word bound to the agent/service, or
  the standalone word billing can route — generic developer wording ("balance this
  binary tree", "check the balance factor", "look for free variables")
  does not inject.
- Bump the Hermes plugin package to `0.21.12`; acknowledge encrypted Slack
  detail receipt immediately in Telegram, report value-blind validation stages
  and stable error codes to the platform, and require a successful owner-DM
  welcome message before the connection is marked ready.
- Add the `tinyhat:tinyhat-privacy`
  skill and widen the `pre_llm_call` context so agents answer privacy and
  data-access questions from the platform's real trust model instead of
  guessing: each user gets a dedicated isolated Computer, conversations and
  files are processed and stored on that Computer, and Tinyhat does not read
  customer Computers' contents as part of routine operations — human access is
  limited to what the user affirmatively requests or permits, what is needed
  to investigate abuse, protect the service, or maintain security, and what
  is required by law; anything else would violate Tinyhat's own Terms and
  Privacy Policy (https://tinyhat.ai/terms, https://tinyhat.ai/privacy).
  The skill keeps answers honest without comparisons (Tinyloop operates the
  underlying infrastructure, so low-level technical access remains possible
  today; private Computers are the direction that removes it) and forbids
  speculating about named operators, enumerating internal access paths, or
  claiming which internal dashboards or tools exist. Privacy routing is a
  dedicated bilingual matcher: word-boundary phrases plus a bounded
  subject+access rule in English and Persian, with Persian spelling
  canonicalization (zero-width joiners, Arabic letter forms) — generic
  developer wording such as "tail the application logs", "operator
  precedence", "my database", or Persian "بلاگ" does not inject on its own.
  Promotion gate: merge only after the matching Computer-wide access
  commitments are live on https://tinyhat.ai/privacy and
  https://tinyhat.ai/terms, re-verify those live pages, and only then
  promote `channels/lts` and `channels/latest`.
- Add `tinyhat_slack_connect`. The tool generates Hermes' current Slack
  Agent-view manifest, removes its workspace-global slash commands and the
  exact `commands` bot scope, sends the create-from-manifest guide in Telegram,
  accepts the bot token, Socket Mode app token, and allowed member IDs as one
  browser-encrypted bundle, validates and saves them on the Computer, and
  leaves all Slack message handling to Hermes over Socket Mode. Direct env
  writes resolve and verify Hermes' real Python runtime from its launcher or
  project venv instead of accepting an unrelated system Python executable.
  Detached handoff workers now also honor the platform's entry window, so the
  Slack worker remains available for the advertised 30-minute setup period.
  The Computer now opens the first allowed member's DM and saves it locally as
  Hermes' Slack home channel, avoiding an unusable slash-command prompt.
- Bump the Hermes plugin package to `0.21.8`; add `tinyhat_credentials` and
  `tinyhat:tinyhat-credentials` for value-blind name/description discovery and
  expiring two-stage Telegram removal. Confirmed deletion is executed by the
  assigned Computer, never by the platform, and the same name can be added
  again after local deletion succeeds.
- Bump the Hermes plugin package to `0.21.7` and separate Tinyhat requestability
  from Google verification state. All nine implemented Gmail, Calendar, and
  Drive scopes can reach Google while verification is `preparing_submission`;
  Google may show its unverified-app warning and the user decides. Unknown,
  unimplemented, and legacy-only scopes still return `review_required` before
  OAuth, and operation-level write confirmation remains unchanged. Merge this
  plugin without moving channels, deploy the matching platform pin first, then
  promote `channels/lts` and `channels/latest`. Teach agents the pinned raw
  `gws` command shape explicitly: dotted method identifiers are for schema
  lookup only, API execution uses split service/resource/method argv, and
  request bodies use `--json` rather than `--params`.
- Bump the Hermes plugin package to `0.21.6`; make a bare Google connection
  identity-only; define five reviewed, composable Workspace access presets in a
  packaged public scope manifest; limit Custom access to manifest-listed
  scopes; and return `review_required` before Google for unknown or unreviewed
  requests. Legacy `profile` values remain compatibility inputs. Merge this
  plugin without promoting release channels; deploy the matching platform
  enforcement before advancing `channels/lts` or `channels/latest`.
- Bump the Hermes plugin package to `0.21.5`; make the recommended Google
  Workspace connection useful for Gmail reading, composing, sending, and
  inbox/draft/label management with `gmail.modify` (messages and threads cannot
  bypass Trash for immediate permanent deletion), Calendar event management,
  and read-only Drive; accept
  bounded canonical Google-owned custom scope sets with a user-facing reason;
  exact-allow Google's official legacy Calendar and Contacts feed scopes with
  explicit disclosure of their full read/write and permanent-deletion power;
  preserve exact legacy profiles; coordinate prepare URL and launch-ticket
  validation with the backend's 32 KiB ceiling so maximum bounded custom scope
  sets survive; and widen the guarded `gws` bridge to bounded Google service
  namespaces while retaining operation-level write confirmation.
- Bump the Hermes plugin package to `0.21.4` for portable, integrity-verified
  `gws` execution from the verified file descriptor and clearer managed-install
  guidance.
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
