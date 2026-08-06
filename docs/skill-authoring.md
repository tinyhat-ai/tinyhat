# Skill Authoring

Tinyhat skills are public instructions that teach an agent how to use a
Tinyhat capability safely.

## Shape

Each skill lives in:

```text
skills/<skill-name>/SKILL.md
```

`SKILL.md` starts with frontmatter:

```yaml
---
name: tinyhat-tell-joke
description: Tell a short Tinyhat wiring-test joke when the user asks for proof that the Tinyhat plugin is installed.
---
```

## Rules

- One skill should do one clear job.
- Use names that describe the user intent and the capability outcome.
- Keep the body short and operational. Put long examples or references in
  linked docs instead of loading them into every agent run.
- Make the frontmatter `description` specific enough to trigger only for
  the intended user request.
- Define any tool inputs with strict schemas and examples that match real
  user wording.
- Put framework-specific loading in adapter files, not in skill text.
- Do not include private platform URLs, tenant data, tokens, or local
  machine paths.
- Do not ask the user to paste secret values in chat.
- For credentials, require meaningful env-style names. Use
  `EXA_API_KEY`, `GITHUB_TOKEN`, or `STRIPE_SECRET_KEY`; never use
  `TINYHAT_SECRET`, `SECRET`, `API_KEY`, or `TOKEN`.
- For Tinyhat-managed Hermes behavior that should be visible before a
  specific skill loads, use a short `pre_llm_call` context hook and keep
  the longer playbook in a skill.
- For Google access, add or revise the public scope manifest first. Skill copy
  may explain manifest presets and scopes, but it must not make an unknown,
  unimplemented, or legacy-only scope sound requestable. Keep requestability
  separate from pending or completed Google verification.
- For capability-discovery skills, include concrete trigger examples in
  the frontmatter description. Example: `tinyhat-codex-auth` names
  "connect you to my ChatGPT account", "use my Codex subscription", and
  "switch from platform credits" so Hermes can load the right playbook
  before it answers with generic model-provider advice.
- When a tool sends its own native Telegram action message, tell the agent not
  to send a duplicate reply. Keep action URLs, tokens, and intent identifiers
  out of tool output and skill examples.
- For destructive actions confirmed by a platform-authenticated user surface,
  do not let the model manufacture confirmation with `confirmed: true`. State
  which final choices are shown, require every terminal outcome to remove its
  buttons, and document what cancellation preserves.
- Add or update tests when changing a skill's tool contract, naming
  behavior, security wording, or framework adapter registration.

## Skill Checklist

- The skill has one user-visible job.
- The trigger description names the exact user intent that should load it.
- The first steps tell the agent what to do, not why skills exist.
- Examples are concrete and safe to copy.
- Tool schemas reject dangerous or generic inputs.
- User-facing messages are short and put the main action first.
- Security claims match the real platform and runtime behavior.
- README, capabilities docs, tests, and adapter metadata stay in sync.

## Secret Naming Standard

When a skill creates or asks for a credential, choose a name that the
user can recognize later without seeing the value.

| Request | Correct name | Avoid |
| --- | --- | --- |
| "Save my Exa API key" | `EXA_API_KEY` | `TINYHAT_SECRET` |
| "Connect my GitHub token" | `GITHUB_TOKEN` | `TOKEN` |
| "Add a Stripe secret key" | `STRIPE_SECRET_KEY` | `API_KEY` |
| "Save the OpenRouter key" | `OPENROUTER_API_KEY` | `SECRET` |

If the provider or purpose is ambiguous, ask one short clarification
question before creating the handoff.

## Tinyhat Platform Context

Use `pre_llm_call` only for short operating context that should be visible
before a specific Tinyhat skill is loaded. Keep the detailed instructions
inside skills so the plugin stays readable and token efficient.

## Current Skills

`hat-authoring` is the M1 create/list/inspect path for shareable hats. It gets
the human name and one customer's work email before create, accepts optional
Telegram bot username and display-name defaults, never asks the
model for owner or account ids, calls `tinyhat_hats`, and reports the
platform-returned handle and share URL. The public page owns email verification
and Telegram agent creation; the skill must not imply that repository content
or hat credentials are already populated. Credential authoring defines names
and purposes without values, then opens one encrypted bundle form after all
fields are ready. The bundle is staged in the Hat's Computer-local package
store for its intended customer, not loaded into the authoring Hermes
environment, and does not trigger a Hermes restart.

`tinyhat-tell-joke` is intentionally small. It proves the plugin is
installed before we add real Tinyhat platform capabilities.

`tinyhat-plugin-version` proves which plugin version Hermes is actually
running. Use it for update tests so we do not confuse admin metadata with
the live plugin code loaded in an agent session.

`tinyhat-skill-catalog` lists the plugin-qualified skill names for Tinyhat
skills. Use it when `skills_list`, `available_skills`, or unqualified
`skill_view` cannot find a Tinyhat plugin skill. It should steer the agent
to retry with names like `tinyhat:tinyhat-codex-auth`.

`tinyhat-private-secret` is the default way to add credentials to Hermes.
It should be triggered before generic `.env` advice whenever a user asks
to add or save an API key, token, password, or credential.

`tinyhat-slack` is the dedicated way to connect the current Hermes agent to
Slack. It must call `tinyhat_slack_connect` once and let the tool own the
Telegram response. Do not split the two tokens into generic secret handoffs,
ask for token values in chat, enable open workspace access, or add a parallel
Slack adapter. Hermes supplies the manifest and owns Socket Mode.
Tinyhat removes slash-command definitions and the `commands` OAuth scope from
that manifest because Slack command names are workspace-global and per-agent
apps must not collide.
For disconnect, the same skill calls `tinyhat_slack_disconnect` once. The
platform owns the expiring two-stage Telegram confirmation, and a detached
plugin worker revokes Slack and removes the whole bundle only after
confirmation. The runtime adds no Slack-specific command; generic credential
removal must remain blocked for individual Slack names.

`tinyhat-credentials` is the value-blind discovery and removal path for those
new secure credentials. It lists names, descriptions, and opaque handoff ids,
never values. For agent-requested removal it calls `tinyhat_credentials` once
with the selected handoff id; the platform owns an expiring two-stage Telegram
confirmation, then Hermes removes the local env entry and terminal alias. Do
not ask for text confirmation or send a duplicate reply. After Computer proof,
Tinyhat deletes the metadata row so the same env name can be added again.

`tinyhat-google-workspace` is the default way to connect existing Google
accounts. Calling connect without `account_id` adds an account. Status exposes
safe metadata and the stable opaque `account_id` used to select an account;
skills must never guess between multiple accounts. Bare connect requests only
`openid`, `email`, and `profile`.

When the user needs Workspace data, the skill chooses the smallest composable
`presets` array from Mail Reader (`mail_reader`), Mail Sender
(`mail_sender`), Workspace Reader (`workspace_reader`), Mail Writer
(`mail_writer`), Inbox Manager (`inbox_manager`), Calendar Coordinator
(`calendar_coordinator`), and File Collaborator (`file_collaborator`).
Mail Sender's `gmail.send` cannot read the inbox or manage drafts. Mail
Writer's `gmail.compose` includes drafts and sending. Inbox Manager's
`gmail.modify` includes reading, composing, sending, drafts, labels, archive,
and read state, but not immediate permanent deletion. Workspace Reader's
`gmail.readonly` also exposes Gmail settings. File Collaborator's implemented
`drive.file` workflow covers files Tinyhat creates or files the user explicitly
shares with the app, not other Drive files.

Custom `scopes` must be exact manifest-listed canonical values with a short
precise `reason`; they may compose with presets. Unknown, unimplemented, or
legacy-only scopes return `review_required` before Google, so a skill must
explain the result and must not retry with broader access. Pending Google
verification remains truthful manifest metadata but does not block an
implemented request; Google may show its own warning. Historical `profile`
values are
compatibility inputs only and cannot be combined with `presets` or `scopes`.
Do not duplicate scope membership in a new skill: read it from the packaged
manifest and loader. Preserve its normalization rules, including
`gmail.modify` over narrower Gmail scopes, `gmail.compose` over `gmail.send`,
and `calendar.events` over `calendar.events.readonly`.
The separate `compatibility_scope_disclosures` records are risk labels for
historical grants and blocked requests only. They must never be presented as
implemented capabilities or selectable permissions. Package validation scans
literal and statically constructed production-Python scope URLs against both
manifest collections and validates the exact structured scope and capability
marker inventories in `docs/capabilities.md`; it does not infer claims from
arbitrary prose.
Connect with an account id is additive, while `set_permissions` is exact
replacement plus identity and can narrow local access without disconnecting.
This is not provider-side granular scope revocation. Google consent is the
permission decision; do not add a plugin elevation confirmation or pass
`confirmed` / `confirmation_id` to permission changes. The skill calls
`tinyhat_google_workspace` instead of
asking for Google Cloud setup, OAuth values, SSH access, or a manual credential
file. The plugin places the platform-authored
Google URL only inside a native Telegram **Connect Google** button. Tool output
and agent replies must never expose a plain authorization link. The platform
owns the central Web OAuth client, callback, exchange,
identity validation, and RSA-encrypted credential delivery; the Computer keeps
the one-time private key and stores the decrypted credentials locally.
The auth skill does not contain Google service operations. It routes
connected service requests through Hermes's bundled `google-workspace` skill for
operation semantics and then through `tinyhat_google_workspace_app` with the
selected `account_id` for bounded execution across Google service namespaces.
Operation-level write confirmation binds account and argv and remains required
independently of OAuth consent. The native skill's OAuth setup and scripts are not used on Tinyhat
Computers. The generic bridge owns credential injection, process bounds, and
redaction. Never send users into `gws auth`, Google Cloud setup, credentials
JSON, or a second OAuth flow.

For revoke or disconnect requests, the skill calls
`tinyhat_google_workspace` with `action=disconnect` and the selected
`account_id` once. The tool sends
an initial native Telegram `web_app` message with exactly one **Revoke this
Computer’s access** button, and the agent sends no duplicate reply, exposes no
action URL, and never passes or claims `confirmed: true`. The first authenticated
tap edits the same message to final **Confirm revoke** and **Cancel** buttons.
Either result removes the buttons.
Cancel preserves credentials. Confirm lets a generation-bound worker delete
only the selected local account before the platform marks that connection
disconnected. Other local accounts remain connected. The skill must describe
this as local-only Tinyhat revocation, not revocation of Google's shared
provider grant; other Computers are unaffected.

If the managed gws app is absent, route to
`tinyhat-google-workspace-app-manager`. Explain the pinned integration and ask
before install or uninstall; never mutate the Computer automatically. Hermes's
built-in skill remains operation guidance only; Tinyhat's token bridge replaces
its local-client authentication and script execution. The skill calls
`tinyhat_google_workspace_app_manager` only after that approval.

`tinyhat-codex-auth` is the default way to connect a Tinyhat-managed
Hermes agent to the user's OpenAI Codex / ChatGPT subscription, and it
carries the funding model: a small included starter credit (about $10)
now, the user's own subscription as the intended ongoing fund. It should
trigger for common user wording such as "connect my ChatGPT account" or
"use my Codex subscription", and for funding questions such as how the
agent is paid for or what happens when credits run out. It should call
`tinyhat_codex_auth` once
with `{"action": "prerequisite"}` so the user receives the ChatGPT
Settings > Security screenshot and `/codex_auth` on its own line. The
skill should not send an extra text reply, duplicate links, or start the
helper twice. It may use `{"action": "status"}`, `{"action": "log"}`, or
`{"action": "limits"}` for follow-up inspection. The once-per-Computer
funding note is directed by the platform context with a durable
marker: a new user's onboarding reply presents the subscription
connection as one of the onboarding steps, a returning user gets one
brief line, and an already-connected subscription skips it. Tool-owned
native first replies satisfy it, and the agent must never state a
remaining credit balance it cannot see.

`tinyhat-plugin-update` checks and applies the configured plugin channel
through installed runtime commands. It should start with
`{"action": "status"}` and require explicit user/operator confirmation
before `{"action": "update", "confirmed": true, "restart_gateway": true}`.

`tinyhat-platform` is the compact operating map for Tinyhat-managed
Hermes agents. It explains secrets, Codex auth commands, usage limit
commands, safe Computer platform status through `tinyhat_get_platform_status`,
skill discovery, plugin updates, reporting guidance, and the
runtime/plugin/platform boundary.

`tinyhat-privacy` is the trust answer for who-can-see-my-data questions.
It gives the agent the platform's real privacy model — dedicated isolated
Computers, no routine platform reading of Computer contents, human access
limited to what the user affirmatively requests or permits, abuse/service
protection and security needs, and legal requirements — plus the honest
comparison-free caveat that Tinyloop operates the underlying
infrastructure today, the private-Computers direction, and links to
https://tinyhat.ai/privacy and https://tinyhat.ai/terms. It forbids
speculating about named operators or claiming which internal tools exist.
