# Tinyhat Plugin

Tinyhat is the public plugin that teaches an agent what the Tinyhat
platform can do for it.

The runtime stays intentionally small: heartbeat, attestation, command
delivery, framework install, and safe update plumbing. This repository is
the part that can evolve faster. It adds the agent-facing skills and tools
that explain how to use Tinyhat platform capabilities without exposing
private platform URLs, machine credentials, bot tokens, or tenant data.

For the first v0.20 version, this repo is deliberately small. It supports
Hermes only, ships two proof skills, and now includes the first real
Tinyhat platform capability: a private secret handoff that lets the user
enter a secret in a Telegram Mini App without sending the plaintext to
Tinyhat's servers.

## What This Plugin Does

| File | Purpose |
| --- | --- |
| `plugin.yaml` | Hermes plugin manifest. |
| `__init__.py` | Hermes registration entrypoint. |
| `hermes.plugin.json` | Tinyhat metadata for the Hermes adapter, skill, command, and release channels. |
| `tools.py` / `schemas.py` | Tinyhat tools: plugin version, joke proof, and private secret handoff. |
| `skills/tinyhat-tell-joke/SKILL.md` | Deterministic joke proof. |
| `skills/tinyhat-plugin-version/SKILL.md` | Live plugin version proof. |
| `skills/tinyhat-private-secret/SKILL.md` | Browser-encrypted secret handoff guidance. |
| `docs/skill-authoring.md` | The standard for future Tinyhat skills. |
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

`tinyhat-private-secret` is the first real capability. When the user asks
to save an API key, token, password, or credential, the agent calls
`tinyhat_private_secret_handoff`. The Computer creates a one-time key
pair, the user enters the value in a Telegram Mini App, the browser
encrypts the value with the public key, and the Computer decrypts it with
the temporary private key. Tinyhat stores only short-lived ciphertext for
the handoff and wipes it after completion, expiration, or failure.

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
TINYHAT_PLUGIN_REF=v0.20.4
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
