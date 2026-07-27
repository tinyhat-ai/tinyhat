# Tinyhat Plugin

Tinyhat is the public plugin that teaches an agent what the Tinyhat
platform can do for it.

The runtime stays intentionally small: heartbeat, attestation, command
delivery, framework install, and safe update plumbing. This repository is
the part that can evolve faster. It adds the agent-facing skills and tools
that explain how to use Tinyhat platform capabilities without exposing
private platform URLs, machine credentials, bot tokens, or tenant data.

This repo is deliberately small. It supports Hermes only, ships a compact set
of packaged skills, a small Tinyhat
context hook, and now includes the first real Tinyhat platform capability:
a private secret handoff that lets the user enter a secret in a Telegram
Mini App without sending the plaintext to Tinyhat's servers. It also
connects multiple existing Google identities to a Computer without asking the
user for a Google Cloud project, OAuth client, secret, or SSH access. A bare
connection requests identity only. Five composable presets cover common
read-only Workspace access, mail writing, inbox management, Calendar event
management, and limited file collaboration. Custom requests can select only
implemented scopes that the packaged public manifest marks requestable for the
active OAuth client. A separate manifest state records whether Google
verification is pending or complete. Google shows the exact request and the
user decides whether to grant it or ask for narrower access. It
teaches the agent the Tinyhat-managed OpenAI Codex / ChatGPT subscription
auth flow that is installed on each Hermes Computer.
It also connects that same Hermes agent to Slack with Hermes' current
Agent-view manifest and Socket Mode adapter. Slack tokens are entered together
in the encrypted Mini App and decrypted only on the Computer; Tinyhat never
receives Slack message content. Tinyhat removes slash commands from each
per-agent manifest so command names cannot collide across apps in one
workspace.

## What This Plugin Does

| File | Purpose |
| --- | --- |
| `plugin.yaml` | Hermes plugin manifest. |
| `__init__.py` | Hermes registration entrypoint. |
| `hermes.plugin.json` | Tinyhat metadata for the Hermes adapter, skill, command, and release channels. |
| `context.py` | Small Hermes `pre_llm_call` context hook for Tinyhat-sensitive turns. |
| `tools.py` / `schemas.py` | Tinyhat tools: plugin version, safe platform status, joke proof, skill catalog, private secret handoff and removal, Slack connection, Google identity connection, Codex auth setup/status helpers, and plugin update helper. |
| `slack_connection.py` | Hermes manifest generation plus Computer-local Slack token validation and installation. |
| `credentials.py` | Value-blind credential name/description discovery and platform-owned, expiring Telegram removal confirmation. |
| `google_workspace.py` / `google_workspace_worker.py` | Platform-authored Google OAuth handoff, multi-account local custody, manifest-governed access selection, assignment-safe status, and targeted disconnect. |
| `google_workspace_scope_manifest.json` / `google_workspace_scope_manifest.py` | Versioned public Google scope contract and dependency-free loader. |
| `google_workspace_app.py` | Account-selected credential bridge to the manifest-verified, root-owned managed `gws` app. |
| `google_workspace_app_manager.py` | Confirmed install/status/uninstall for pinned official `gws` Linux artifacts. |
| `skills/tinyhat-tell-joke/SKILL.md` | Deterministic joke proof. |
| `skills/tinyhat-plugin-version/SKILL.md` | Live plugin version proof. |
| `skills/tinyhat-skill-catalog/SKILL.md` | Skill discovery guidance for plugin-qualified Tinyhat skill names. |
| `skills/tinyhat-private-secret/SKILL.md` | Browser-encrypted secret handoff guidance. |
| `skills/tinyhat-slack/SKILL.md` | Hermes-native Slack Agent-view and Socket Mode onboarding. |
| `skills/tinyhat-credentials/SKILL.md` | Value-blind credential discovery and confirmed Computer-side removal guidance. |
| `skills/tinyhat-google-workspace/SKILL.md` | Existing-account Google identity connection guidance. |
| `skills/tinyhat-google-workspace-app-manager/SKILL.md` | Approval-gated managed `gws` installation guidance. |
| `skills/tinyhat-codex-auth/SKILL.md` | OpenAI Codex / ChatGPT subscription auth guidance. |
| `skills/tinyhat-plugin-update/SKILL.md` | Channel update guidance for stale installed plugin checkouts. |
| `skills/tinyhat-platform/SKILL.md` | Platform context for Tinyhat-managed Hermes agents. |
| `skills/tinyhat-privacy/SKILL.md` | Privacy and trust model guidance: who can see user data, and when. |
| `docs/skill-authoring.md` | The standard for future Tinyhat skills. |
| `.agents/skills/tinyhat-plugin-skill-authoring/SKILL.md` | Maintainer workflow for adding or changing plugin skills. |
| `RELEASING.md` | How releases and `channels/lts` / `channels/latest` work. |

There is no legacy framework adapter in this branch. Additional framework
adapters will come later as separate, small files once the Hermes path is
proven.

## Trust Boundary

Tinyhat managed Computers call Tinyhat platform APIs through the runtime's
attested Computer identity. That identity lets the platform know which
Computer, agent, user, and account are involved.

This plugin does not mint identity. The Tinyhat platform owns one central Google
Web OAuth client and callback, validates the exact manifest-requestable capability
request, exchanges the one-time code, and encrypts
the resulting credential envelope to the
Computer's one-time RSA public key. The plugin stores credentials only after the
assigned Computer decrypts and revalidates that envelope. It never prints or
returns the code, private key, or tokens. The platform handles tokens transiently
and retains only short-lived ciphertext for the handoff. The local
multi-account credential registry is not
application-encrypted at rest: it is protected by a `0700` owner directory and
`0600` owner-only file permissions. It does not
call private platform APIs directly from random shell snippets. Its job is
to teach the agent how to use named Tinyhat capabilities that the runtime
and platform make available.

That separation matters:

- The runtime remains boring and stable.
- The plugin remains readable and easy to update.
- Users can inspect which skills and tools are being installed.
- Privileged actions can stay behind platform APIs and Telegram buttons.

## Current Skills

`tinyhat-tell-joke` is a wiring proof. When the user asks whether the
Tinyhat plugin is available, or asks for a joke, the agent can call
`tinyhat_tell_joke`. The result is intentionally simple so we can test the
whole installation path before adding real platform capabilities.

`tinyhat-plugin-version` is the update proof. When the user asks which
Tinyhat plugin version is running, the agent can call
`tinyhat_plugin_version`. The answer comes from the plugin code loaded by
Hermes, not from admin metadata or a GitHub branch name.

`tinyhat_get_platform_status` reads the existing Computer-authenticated
platform status endpoint. It returns only safe Computer state, assignment,
configuration revision, and package inventory metadata; it never returns
tokens, credentials, or private platform URLs.

`tinyhat-skill-catalog` is the discovery repair path. When `skills_list`,
`available_skills`, or an unqualified `skill_view(name="tinyhat-codex-auth")`
does not show Tinyhat plugin skills clearly, the agent calls
`tinyhat_skill_catalog`. The result lists `tinyhat:<skill-name>` qualified
names, unqualified aliases, paths, and purposes so the agent can retry with
the correct qualified skill name instead of guessing from a not-found error.

`tinyhat-private-secret` is the first real capability. When the user asks
to save an API key, token, password, or credential, the agent calls
`tinyhat_private_secret_handoff`. The Computer creates a one-time key
pair, the user enters the value in a Telegram Mini App, the browser
encrypts the value with the public key, and the Computer decrypts it with
the temporary private key. Tinyhat stores only short-lived ciphertext for
the handoff and wipes it after completion, expiration, or failure. After
the Computer saves the secret locally, the saver worker registers the name
for terminal env passthrough, sends one short Telegram notice, and claims
the handoff with `outcome="installed_restart_pending"`. The Tinyhat
platform then queues the runtime's one-shot gateway restart and sends the
final ready-or-failed confirmation after that restart command settles —
the worker never stops, starts, or restarts the gateway itself. The worker
still runs outside the Telegram gateway service (a transient systemd unit
when available) as defense in depth. The runtime reloads Hermes env files
during gateway startup and records Tinyhat-managed terminal aliases for
the saved names, so exec/shell subprocesses can use the secret without
Tinyhat storing or returning the value.

`tinyhat-slack` connects the existing Hermes agent to Slack without a public
endpoint or SSH. `tinyhat_slack_connect` runs `hermes slack manifest
--agent-view`, sends that JSON plus a highlighted create-from-manifest guide,
and opens one encrypted Mini App form for the `xoxb-` bot token, `xapp-`
Socket Mode token, and allowed Slack member IDs. The Computer validates those
values against Slack, saves them through Hermes' supported configuration
interface, and reports only the app and workspace identifiers needed by the
Connections page. Hermes owns the WebSocket and every Slack message.
Before the JSON is sent, the plugin removes Hermes' slash-command definitions
and the `commands` OAuth scope so multiple per-agent apps can coexist in the
same workspace without command-name conflicts.

`tinyhat-credentials` lists only the safe names, descriptions, and saved
timestamps of credentials currently installed through the private-secret
handoff. Removal sends an expiring two-stage Telegram confirmation. After the
user confirms, the platform queues a generation-bound runtime command; Hermes
deletes the env entry, terminal alias, and loaded process value locally. The
platform hard-deletes the value-less credential metadata only after that local
proof, and the user may then add the same name again.

`tinyhat-google-workspace` connects this Computer to existing Google accounts.
Each connect without `account_id` adds an account while preserving the others.
The Computer creates a fresh RSA keypair and asks the
platform for identity only: `openid`, `email`, and `profile`. Workspace data
access is explicit and comes from the versioned
`google_workspace_scope_manifest.json` contract (schema
`tinyhat_google_workspace_scope_manifest_v1`, manifest version `1.0.1`). It
defines these composable presets:

| Preset | Id | Exact data scope |
| --- | --- | --- |
| Workspace Reader | `workspace_reader` | `https://www.googleapis.com/auth/gmail.readonly` for messages, threads, and Gmail settings; `https://www.googleapis.com/auth/calendar.events.readonly`; and `https://www.googleapis.com/auth/drive.readonly` |
| Mail Writer | `mail_writer` | `https://www.googleapis.com/auth/gmail.compose` for drafts and sending |
| Inbox Manager | `inbox_manager` | `https://www.googleapis.com/auth/gmail.modify` for reading, composing, sending, drafts, labels, archive, and read state, without immediate permanent deletion |
| Calendar Coordinator | `calendar_coordinator` | `https://www.googleapis.com/auth/calendar.events` for event read/write |
| File Collaborator | `file_collaborator` | `https://www.googleapis.com/auth/drive.file` for files Tinyhat creates or files you explicitly share with the app; no access to other Drive files |

Custom access is an exact subset or union of manifest-listed scopes and may be
combined with presets. The loader normalizes redundant scopes so
`gmail.modify` supersedes Gmail read, compose, send, and label-only access;
`gmail.compose` supersedes `gmail.send`; and `calendar.events` supersedes
`calendar.events.readonly`. Historical `profile` values remain compatibility
inputs for older callers and saved grants, not the path for new requests.

Every manifest scope records a stable id, canonical URL, Google classification,
enabled API, implemented features and operations, data read or written,
narrower alternatives, user copy, demo steps, and separate per-client request
and verification states. The nine implemented Gmail, Calendar, and Drive
scopes remain requestable while Google verification is
`preparing_submission`; Google may show its own unverified-app warning before
the user decides. Unknown, unimplemented, or legacy-only scopes return a
structured `review_required` result before OAuth state is created, a worker
starts, or a Google button is sent. This lets Tinyhat document a future
capability without making it requestable in production.
Historical saved grants and blocked requests can also use the manifest's
separate `compatibility_scope_disclosures` risk labels. These disclosure-only
records define no capability or operation and can never make a scope
requestable. Package validation checks literal and statically constructed
production scope URLs against those two explicit collections.

The platform returns its Google sign-in URL to the plugin, which places it only
inside a native Telegram inline button labeled **Connect Google**. The tool
never returns a plain authorization link. The user supplies only their existing
Google account; they never provide a Google Cloud project, OAuth client, or
secret.

Google posts the code to Tinyhat's fixed HTTPS callback. The platform validates
state, exchanges the code through its central Web OAuth client, verifies the
identity and exact scopes, and RSA-encrypts the credential envelope to the
Computer's one-time public key. A detached plugin worker polls terminal handoff
state, decrypts a ready envelope, revalidates assignment and the accepted bundle,
and atomically saves the account in the owner-only
`~/.tinyhat/google-workspace/accounts.json` registry. Cancelled, failed,
expired, and superseded attempts stop
with fixed safe outcomes. The worker and status path revalidate the credential's
current Computer assignment. An owner-only active-generation marker plus one
local lifecycle lock ensures that reconnect or disconnect supersedes older
workers. Invalid owner-only credential entries and pending handoffs are wiped
together under that lock. Status exposes only safe account metadata, including
the platform's stable connection id as opaque `account_id`. A locked migration
imports the former singleton `credentials.json` only after exactly one safe
platform connection matches its email and bundle; otherwise it leaves the
legacy file intact and refuses mutation.

When the user asks to revoke one connection, the agent selects its `account_id`
from status and calls `tinyhat_google_workspace` once with
`action=disconnect`. The tool
starts a short-lived, assignment-bound request and sends an initial Telegram
`web_app` message with exactly one **Revoke this Computer’s access** button. It
returns no action URL, token, or intent identifier to the model, and the agent
sends no duplicate reply. The model never passes or claims `confirmed: true`
for disconnect.

The first authenticated tap edits that same Telegram message to show final
**Confirm revoke** and **Cancel** buttons. Either final choice
removes the buttons. Cancel preserves the local credential and connection
metadata. Confirm wakes a generation-bound Computer worker, which deletes only
the selected local account under the lifecycle lock and then reports the result
so the platform can mark that connection disconnected. Other accounts remain
connected. A stale confirmation cannot delete credentials installed by a later
permission change.

This ceremony revokes Tinyhat access on this Computer only. It does not call
Google's token-revocation endpoint or revoke the provider grant in the shared
development OAuth project. Other Tinyhat Computers are unaffected, and the
plugin must never claim that the Google account's provider grant was revoked.

`presets` is an array because common jobs often need more than one capability.
For example, Mail Writer and Calendar Coordinator can be requested together
without adding inbox-management or broad Drive access. Manifest-listed Custom
scopes can be included in the same request with a short user-facing reason.
`connect` with an `account_id` unions the requested access with that account's
current set, while `action=set_permissions` replaces the selected account with
the exact requested presets and Custom scopes, plus identity. A narrower
replacement makes this Computer stop using removed scopes; it does not perform
Google provider-side granular revocation or erase consent history.

Google's consent screen is the permission decision. A cancelled, failed, or
expired change leaves the existing local credential untouched; a valid
encrypted credential replaces only the selected entry atomically. Google
consent never counts as confirmation for an actual email send, label or draft
mutation, Calendar event change, Drive write, or other external operation. If
Google returns a different scope set, Tinyhat saves no new Computer credential
and tells the user to choose the exact narrower access before another request.

The authentication plugin does not implement mail, event, or file operations.
Hermes's bundled `google-workspace` skill supplies operation semantics while the
external managed `gws` app performs the API call through Tinyhat's bridge. Its
local-client OAuth setup and scripts are intentionally bypassed.

`tinyhat_google_workspace_app` is a generic credential bridge. It accepts only
bounded opaque argv from Hermes's native Google Workspace skill, selects the
requested `account_id`, verifies the Computer assignment, refreshes only that
entry through the platform broker when needed, and injects its access token only
into one isolated, root-owned `gws` child process.
The bridge accepts only the API namespaces audited for the pinned `gws` release
and only executes `/opt/tinyhat/bin/gws` when the app manager's root-only manifest matches the
hardcoded version, architecture, source, mode, and SHA-256. It never passes the refresh token,
client secret, credential file, executable, environment, or working directory
from agent input. The bridge blocks the complete `gws auth` namespace,
unaudited or synthetic roots, setup/login/export credential flows, file-I/O and
external-sanitization flags, persistent server mode, and unbounded pagination.
A Google scope can be connected before this pinned CLI exposes an operation for
it. Output and execution time are
hard-bounded, access-token values are defensively redacted, and every result is
marked as untrusted external content.

`tinyhat_google_workspace_app_manager` is the reproducible install path. It
supports pinned official Linux x86_64 and aarch64 release archives, verifies
hardcoded archive and extracted-binary SHA-256 values, rejects unsafe archive
entries, and transactionally installs only the binary. Hermes already bundles
Google Workspace operation guidance. Install and uninstall require explicit
approval. A confirmed reinstall from plugin 0.21.0 retires its obsolete managed
operation skills and quarantines modified copies; Hermes's bundled skill and
unmanaged files are untouched. The agent uses the existing Tinyhat token bridge
and never runs `gws auth` or Hermes's local-client setup scripts.

Current security boundary: Hermes, plugin tools, and terminal commands run as
uid 0 on the Computer, the same owner that can read the `0600` Google credential
file. The managed bridge prevents ordinary tool output, argv, inherited-env,
path-replacement, and modified-skill leakage, but it cannot protect a token from
a malicious root-running agent process that reads files or process memory/env
directly. Privilege-separating credential custody and the app broker is future
production hardening. Likewise, a write `confirmation_id` deterministically
binds one selected account and unchanged argv, but is not cryptographic proof of
human presence; the explicit current user instruction or confirmation remains
the authorization for this development flow.

The user never supplies a Google Cloud project, OAuth client, client secret,
credentials JSON, app password, `gcloud` login, or second OAuth flow. If access
needs reauthorization, it goes through Tinyhat again. The same boundary can add
separately reviewed named bundles and external app integrations later without
changing the runtime. The disconnect ceremony also stays inside the existing
plugin-and-platform boundary; it adds no runtime callback or command.

`tinyhat-codex-auth` teaches the agent how to start and inspect the
Tinyhat-managed OpenAI Codex / ChatGPT subscription sign-in flow. When
the user says "connect you to my ChatGPT account", "use my Codex
subscription", or "switch from platform credits", the agent calls
`tinyhat_codex_auth` with `{"action": "prerequisite"}`. The helper sends
the ChatGPT Settings > Security screenshot with the `/codex_auth`
command on its own line so it is hard to miss. That slash command starts
the installed Tinyhat Codex auth helper, which sends the authorization
button and copyable code. The same tool also exposes `status`, `log`, and
`limits` actions for bounded inspection. The agent should not send a
duplicate text reply, call the prerequisite tool twice, ask the user to
choose between unrelated interpretations, or give manual `hermes auth`
instructions.

`tinyhat-plugin-update` teaches the agent how to handle an installed plugin
that is behind `channels/lts` or `channels/latest`. The agent starts with
`tinyhat_plugin_update` `{"action": "status"}`. If the runtime reports
`update_available=true` or `decision=target_ref_changed`, it applies the
update only after the user/operator asks for it by calling
`{"action": "update", "confirmed": true, "restart_gateway": true}`. The
tool uses the installed runtime's `tinyhat_plugin_status`,
`update_tinyhat_plugin`, `stop_hermes`, and `start_hermes` commands rather
than ad hoc shell snippets.

`tinyhat-platform` is the operating context. It tells the agent that
Tinyhat secrets are the default way to add credentials to Hermes and that
Tinyhat's installed Codex auth commands should be used for OpenAI Codex
auth and limit checks. It also routes stale-plugin reports through
`tinyhat_plugin_update`, skill discovery failures through
`tinyhat_skill_catalog`, and Tinyhat QA reports through native reporting
tools instead of arbitrary terminal commands. A small `pre_llm_call` hook
injects only the short version of that context on first turn or when the
user mentions secrets, credentials, Tinyhat, Codex auth, usage limits,
skill lookup, plugin updates, QA reports, or privacy and data-access
questions.

`tinyhat-privacy` is the trust answer. When a user asks who can read
their messages, whether Tinyhat staff or operators see logs or
conversations, or how isolated their Computer is, the agent answers from
the platform's real model instead of guessing: each user gets a dedicated
isolated Computer, conversations and files are processed and stored on
that Computer, and Tinyhat does not read customer Computers' contents as
part of routine operations. Human access is limited to what the user
affirmatively requests or permits, what is needed to investigate abuse,
protect the service, or maintain security, and what is required by law —
anything else would violate Tinyhat's own Terms and Privacy Policy
(https://tinyhat.ai/privacy and https://tinyhat.ai/terms). The skill also
keeps the answer honest without comparisons: Tinyloop operates the
underlying infrastructure, so low-level technical access remains possible
today, which is why the policy is binding and why Tinyhat is building
private Computers designed to remove even that technical possibility.

## Installing

Tinyhat-managed Hermes Computers install from the LTS channel by default:

```bash
TINYHAT_PLUGIN_REPO_URL=https://github.com/tinyhat-ai/tinyhat.git
TINYHAT_PLUGIN_REF=channels/lts
```

The runtime resolves that ref, prepares a local checkout, then asks Hermes
to install the plugin using Hermes' public plugin command:

```bash
hermes plugins install file:///path/to/tinyhat-checkout --enable --force
```

For development or manual testing, use `channels/latest` or an exact tag:

```bash
TINYHAT_PLUGIN_REF=channels/latest
TINYHAT_PLUGIN_REF=v0.21.9
```

## Channels

| Channel | Meaning |
| --- | --- |
| `channels/lts` | Conservative default for managed Computers. |
| `channels/latest` | Newest promoted final version, used when we want faster adoption. |
| exact tag, for example `v0.21.9` | Immutable version for tests, rollbacks, and audits. |

For v0.21.9, merge and tag the public plugin without advancing either channel.
Deploy the platform that validates the same manifest contract, then promote
`channels/latest` and `channels/lts`. This order prevents old Computers or an
older platform from applying the superseded pending-review denial.

## Local Checks

```bash
python3 scripts/validate_framework_package.py
python3 -m unittest discover -s test -p "*.py"
python3 -m compileall -q .
```

## Roadmap

The next skills will continue this pattern: small, inspectable plugin
tools that call versioned Tinyhat platform APIs through the Computer's
attested identity. Runtime code should stay boring and stable.
