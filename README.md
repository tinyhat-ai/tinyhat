# Tinyhat OpenClaw Platform Plugin

[![CI](https://github.com/tinyhat-ai/tinyhat/actions/workflows/ci.yml/badge.svg)](https://github.com/tinyhat-ai/tinyhat/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/tag/tinyhat-ai/tinyhat?label=version&sort=semver)](https://github.com/tinyhat-ai/tinyhat/releases)

Tinyhat is the public platform plugin package for Tinyhat-managed
OpenClaw Computers.

Tinyhat installs this repository into each managed OpenClaw runtime so
the agent can discover the Tinyhat capabilities around it: credential
entry, Manage Computer, terminal entry, safe status, installed package
inventory, and redacted support context.

This repository is intentionally separate from the OpenClaw runtime
package.
The runtime boots OpenClaw, supervises it, applies config, and pins this
plugin repo/ref.
This plugin owns the agent-facing Tinyhat capability tools, the public
manifest, and the default skills that teach the agent which capability
to use.

## What Ships Here

| Surface | Purpose |
| --- | --- |
| [`openclaw.plugin.json`](openclaw.plugin.json) | OpenClaw plugin manifest and capability contract metadata. |
| [`src/index.js`](src/index.js) | Tinyhat tool plugin implementation. |
| [`skills/tinyhat-platform/SKILL.md`](skills/tinyhat-platform/SKILL.md) | Router skill that maps broad Tinyhat/OpenClaw platform intent to focused default skills. |
| [`skills/`](skills) | Focused default skills for secrets, Computer access, runtime status, package inventory, and support reports. |
| [`docs/capabilities.md`](docs/capabilities.md) | Public operation list, safety rules, and response boundaries. |
| [`docs/architecture.md`](docs/architecture.md) | Runtime-vs-plugin ownership boundary. |
| [`docs/skill-authoring.md`](docs/skill-authoring.md) | Standard for authoring packaged Tinyhat skills. |

The skill-authoring standard that governs those skills lives in
[`docs/skill-authoring.md`](docs/skill-authoring.md).

## Default Skill Architecture

The default skill layer is intentionally split into a thin router plus
focused skills:

| Skill | Owns |
| --- | --- |
| [`tinyhat-platform`](skills/tinyhat-platform/SKILL.md) | Routes broad platform requests to the right focused skill and named operation. |
| [`tinyhat-secrets`](skills/tinyhat-secrets/SKILL.md) | Secret-entry buttons and secret metadata listing. |
| [`tinyhat-computer-access`](skills/tinyhat-computer-access/SKILL.md) | Manage Computer and terminal button flows. |
| [`tinyhat-runtime-status`](skills/tinyhat-runtime-status/SKILL.md) | Runtime/environment explanation and restart/reload boundaries. |
| [`tinyhat-package-inventory`](skills/tinyhat-package-inventory/SKILL.md) | Tinyhat-installed defaults versus user-installed package inventory. |
| [`tinyhat-support-report`](skills/tinyhat-support-report/SKILL.md) | Redacted support reports for platform problems. |

The plugin layer exposes tools, button payloads, environment facts, and
redacted diagnostics.
The skills decide when to call those tools and how to respond safely.

## Capabilities

The first package exposes these named Tinyhat operations:

| Operation | Tool | User surface |
| --- | --- | --- |
| `credentials.open_add_secret` | `tinyhat_request_runtime_secret` | Telegram Mini App button. |
| `credentials.list_metadata` | `tinyhat_list_runtime_secrets` | Metadata-only tool result. |
| `computer.open_manage` | `tinyhat_open_manage_computer_link` | Telegram Mini App button. |
| `computer.open_terminal` | `tinyhat_open_terminal_link` | Telegram Mini App button with optional admin-reviewed command. |
| `computer.status` | `tinyhat_get_platform_status` | Secret-free runtime/platform status. |
| `packages.list_installed` | `tinyhat_list_installed_packages` | Public refs/SHAs and Tinyhat-vs-user package split when available. |
| `subscriptions.open_prerequisite_help` | `tinyhat_open_chatgpt_subscription_prerequisite_help` | Telegram photo plus walkthrough text. |
| `subscriptions.open_link` | `tinyhat_open_chatgpt_subscription_link` | Telegram URL button plus bare device-code bubble. |
| `subscriptions.revert_to_platform_credits` | `tinyhat_revert_to_platform_credits` | Metadata-only tool result. |
| `support.report_problem` | `tinyhat_report_problem` | Redacted support context. |

Secret values, signed Mini App intent tokens, raw backend URLs, and
private Computer URLs are not agent-facing output.
Privileged user actions should render as Telegram buttons.
If a channel cannot render a button, the agent should explain the
limitation instead of pasting a Mini App URL into chat.

## Installation

Tinyhat-managed Computers install this package during runtime startup.
The platform passes the public repo and ref through the Computer
provisioning manifest:

```bash
TINYHAT_PLATFORM_PLUGIN_REPO_URL=https://github.com/tinyhat-ai/tinyhat.git
TINYHAT_PLATFORM_PLUGIN_REPO_REF=main
```

The OpenClaw runtime clones that ref and runs:

```bash
openclaw plugins install /path/to/tinyhat --force
```

For local package validation from this checkout:

```bash
python3 scripts/validate_openclaw_package.py
node --check src/index.js
```

## Verifying the Plugin Actually Loads

Installed is not loaded: OpenClaw skips an enabled extension it cannot
read or import without failing the gateway, and
`openclaw plugins inspect` attests registration, not loadability. Two
mechanisms make a load failure loud instead of a silent capability
loss:

- **Load beacon.** When the extension module evaluates successfully it
  logs one line (`[tinyhat] plugin loaded vX.Y.Z …`) and best-effort
  writes `tinyhat-plugin-loaded.json` (plugin, version, `loaded_at`,
  `pid`, `node`) under `$OPENCLAW_STATE_DIR` (fallback `~/.openclaw`).
  Host supervisors can treat "plugin enabled but no fresh beacon after
  gateway start" as a load failure. The beacon never breaks the load:
  write errors degrade to the log line.

- **Loadability self-check.** Run it as the user the gateway runs as,
  against a checkout or an installed extension directory:

  ```bash
  node scripts/check_plugin_load.mjs [--plugin-dir <dir>] [--require-import]
  ```

  It verifies the manifests, that `src/` and every manifest-declared
  skills root exist, ship skills, and are readable by the current user
  (the classic failure: a privileged installer leaves the tree
  root-owned while the gateway runs unprivileged), and — when the
  `openclaw` package is resolvable next to the plugin — that the
  extension entry imports and registers every tool declared in
  `openclaw.plugin.json` `contracts.tools` (a hardcoded floor guards
  against truncated manifests). Exit code 0 means loadable; failures
  name the exact broken path or missing tool.

CI runs the self-check against each supported OpenClaw version,
installs the plugin the way a deployment does, and reproduces the
root-owned-files case to assert it fails loudly (see the
`plugin-load` job in `.github/workflows/ci.yml`).

## Repository Boundaries

- `tinyhat-ai/tinyhat` owns Tinyhat's OpenClaw plugin, capability
  tools, default skills, references, and public release metadata.
- `tinyloophub/tinyhat--runtimes--openclaw` owns OpenClaw boot,
  supervisor, config/apply, health, and pinning this plugin source.
- `tinyloophub/tinyloop` owns platform APIs, provisioning,
  Computer metadata, inventory, canary, hold/pin, rollback, and the
  gitlink/ref Tinyhat deploys.

Do not move platform backend code, runtime boot scripts, tenant
secrets, internal URLs, or private docs into this repository.

## Development

See [docs/local-development.md](docs/local-development.md) for local
checks, [docs/skill-authoring.md](docs/skill-authoring.md) for
packaged-skill standards, and [AGENTS.md](AGENTS.md) for contribution
rules.
