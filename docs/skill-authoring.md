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

`tinyhat-google-workspace` is the default way to connect existing Google
accounts. Calling connect without `account_id` adds an account. Status exposes
safe metadata and the stable opaque `account_id` used to select an account;
skills must never guess between multiple accounts. The default profile grants
identity plus read-only Gmail, Calendar, and Drive access. Exact named
`workspace_readonly`, `gmail_send`, `calendar_write`, and
`gmail_send_calendar_write` profiles let the user replace one local credential
so the Computer adds or stops using write access without disconnecting. This is
not provider-side granular scope revocation. Adding write permission requires
explicit elevation confirmation plus an unchanged retry carrying the returned
`confirmation_id`; removing it does not. The plugin never accepts raw scopes, and
the Gmail profile does not add draft management. The skill calls
`tinyhat_google_workspace` instead of
asking for Google Cloud setup, OAuth values, SSH access, or a manual credential
file. The plugin requests a fixed reviewed bundle and places the platform-authored
Google URL only inside a native Telegram **Connect Google** button. Tool output
and agent replies must never expose a plain authorization link. The platform
owns the central Web OAuth client, callback, exchange,
identity validation, and RSA-encrypted credential delivery; the Computer keeps
the one-time private key and stores the decrypted credentials locally.
The auth skill does not contain Gmail, Calendar, or Drive operations. It routes
connected service requests through Hermes's bundled `google-workspace` skill for
operation semantics and then through `tinyhat_google_workspace_app` with the
selected `account_id` for bounded execution. Write confirmation binds account
and argv. The native skill's OAuth setup and scripts are not used on Tinyhat
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
Hermes agent to the user's OpenAI Codex / ChatGPT subscription. It should
trigger for common user wording such as "connect my ChatGPT account" or
"use my Codex subscription". It should call `tinyhat_codex_auth` once
with `{"action": "prerequisite"}` so the user receives the ChatGPT
Settings > Security screenshot and `/codex_auth` on its own line. The
skill should not send an extra text reply, duplicate links, or start the
helper twice. It may use `{"action": "status"}`, `{"action": "log"}`, or
`{"action": "limits"}` for follow-up inspection.

`tinyhat-plugin-update` checks and applies the configured plugin channel
through installed runtime commands. It should start with
`{"action": "status"}` and require explicit user/operator confirmation
before `{"action": "update", "confirmed": true, "restart_gateway": true}`.

`tinyhat-platform` is the compact operating map for Tinyhat-managed
Hermes agents. It explains secrets, Codex auth commands, usage limit
commands, skill discovery, plugin updates, reporting guidance, and the
runtime/plugin/platform boundary.
