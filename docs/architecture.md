# Architecture

Tinyhat is the OpenClaw platform plugin package installed into
Tinyhat-managed Computers.

The package has one job: teach the agent the safe, named Tinyhat
capabilities available around it.

## Package Shape

```text
tinyhat/
├── openclaw.plugin.json       OpenClaw manifest and capability contract
├── package.json               package version and OpenClaw extension entry
├── src/index.js               tool plugin implementation
├── skills/tinyhat-platform/   compact default skill for agent routing
└── docs/                      public capability and boundary docs
```

## Runtime Flow

```text
Tinyhat platform
  provisions Computer + repo/ref metadata
        |
        v
OpenClaw runtime package
  boots OpenClaw, clones this repo, installs plugin
        |
        v
Tinyhat plugin package
  registers tools + default skills in OpenClaw
        |
        v
Agent
  uses named capabilities instead of raw Tinyhat URLs
```

## Capability Surface

The manifest declares a compact contract:

- `credentials.open_add_secret`
- `credentials.list_metadata`
- `computer.open_manage`
- `computer.open_terminal`
- `computer.status`
- `packages.list_installed`
- `support.report_problem`

The JavaScript plugin maps those operations to HAPI calls using the
Computer identity token or local development bearer configuration.
User-facing privileged actions return Telegram Mini App button payloads.
Secret values and signed Mini App URLs are not printed in chat.

## Boundary

This repo owns:

- OpenClaw plugin metadata.
- Tinyhat tool names and parameters.
- Button-presentation policy for agent-visible responses.
- Default skills that route user intent to the correct tool.
- Public package release metadata.

The OpenClaw runtime repo owns boot, supervision, apply/config, health,
rollback, and cloning/pinning this repo.

The Tinyhat platform owns authenticated backend endpoints, Computer
assignment, provisioning, Telegram Mini App authentication, package
inventory, and rollout policy.
