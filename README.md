# Tinyhat Plugin

Tinyhat is the public plugin that teaches an agent what the Tinyhat
platform can do for it.

The runtime stays intentionally small: heartbeat, attestation, command
delivery, framework install, and safe update plumbing. This repository is
the part that can evolve faster. It adds the agent-facing skills and tools
that explain how to use Tinyhat platform capabilities without exposing
private platform URLs, machine credentials, bot tokens, or tenant data.

For the first v0.20 version, this repo is deliberately small. It supports
Hermes only, ships a compact set of packaged skills, a small Tinyhat
context hook, and now includes the first real Tinyhat platform capability:
a private secret handoff that lets the user enter a secret in a Telegram
Mini App without sending the plaintext to Tinyhat's servers. It also
teaches the agent the Tinyhat-managed OpenAI Codex / ChatGPT subscription
auth flow that is installed on each Hermes Computer.

## What This Plugin Does

| File | Purpose |
| --- | --- |
| `plugin.yaml` | Hermes plugin manifest. |
| `__init__.py` | Hermes registration entrypoint. |
| `hermes.plugin.json` | Tinyhat metadata for the Hermes adapter, skill, command, and release channels. |
| `context.py` | Small Hermes `pre_llm_call` context hook for Tinyhat-sensitive turns. |
| `tools.py` / `schemas.py` | Tinyhat tools: plugin version, joke proof, skill catalog, private secret handoff, Codex auth setup/status helpers, and plugin update helper. |
| `skills/tinyhat-tell-joke/SKILL.md` | Deterministic joke proof. |
| `skills/tinyhat-plugin-version/SKILL.md` | Live plugin version proof. |
| `skills/tinyhat-skill-catalog/SKILL.md` | Skill discovery guidance for plugin-qualified Tinyhat skill names. |
| `skills/tinyhat-private-secret/SKILL.md` | Browser-encrypted secret handoff guidance. |
| `skills/tinyhat-codex-auth/SKILL.md` | OpenAI Codex / ChatGPT subscription auth guidance. |
| `skills/tinyhat-plugin-update/SKILL.md` | Channel update guidance for stale installed plugin checkouts. |
| `skills/tinyhat-platform/SKILL.md` | Platform context for Tinyhat-managed Hermes agents. |
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

This plugin does not mint identity. It does not store tokens. It does not
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
skill lookup, plugin updates, or QA reports.

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
TINYHAT_PLUGIN_REF=v0.20.10
```

## Channels

| Channel | Meaning |
| --- | --- |
| `channels/lts` | Conservative default for managed Computers. |
| `channels/latest` | Newest promoted final version, used when we want faster adoption. |
| exact tag, for example `v0.20.3` | Immutable version for tests, rollbacks, and audits. |

During the v0.20 build-out, both channels may point at this reviewed
branch so Computers can install the fresh Hermes plugin shape before it
replaces `main`.

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
