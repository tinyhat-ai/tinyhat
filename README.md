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
| [`skills/tinyhat-platform/SKILL.md`](skills/tinyhat-platform/SKILL.md) | Compact first skill that teaches the agent the named platform operations. |
| [`docs/capabilities.md`](docs/capabilities.md) | Public operation list, safety rules, and response boundaries. |
| [`docs/architecture.md`](docs/architecture.md) | Runtime-vs-plugin ownership boundary. |

The focused router/default-skills expansion is tracked in
[tinyhat-ai/tinyhat#94](https://github.com/tinyhat-ai/tinyhat/issues/94).
The skill-authoring standard that governs those skills is tracked in
[tinyhat-ai/tinyhat#95](https://github.com/tinyhat-ai/tinyhat/issues/95).

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
checks and [AGENTS.md](AGENTS.md) for contribution rules.
