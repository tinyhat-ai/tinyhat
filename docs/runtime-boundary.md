# Runtime Boundary

Tinyhat's OpenClaw integration is split across public packages.

## Runtime Package

`tinyhat--runtimes--openclaw` owns:

- bootstrapping OpenClaw on the Computer;
- supervising the gateway;
- applying config and Computer-scoped secret files;
- runtime health, diagnostics, and rollback hooks;
- cloning and pinning this plugin repo/ref.

It must not own Tinyhat's agent-facing plugin tools, default skills, or
Telegram presentation policy.

## Plugin Package

`tinyhat-ai/tinyhat` owns:

- `openclaw.plugin.json`;
- `src/index.js` tool plugin implementation;
- the `skills/` package injected into OpenClaw;
- public capability names and response contracts;
- docs that a public reader can understand without private Tinyhat
  repositories.

## Platform Package

Tinyloop's platform backend owns:

- authenticated HAPI endpoints;
- Computer provisioning and assignment;
- public repo/ref/commit metadata;
- Manage Computer and Telegram Mini App auth;
- canary, hold/pin, and rollback orchestration.

This repository may name backend operation intent, but it must not
document private endpoints as agent instructions.
