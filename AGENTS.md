# Tinyhat Plugin Agent Guide

This is the public Tinyhat plugin package. `main` supports Hermes only.

## Boundaries

- Keep user-facing behavior under its owning `capabilities/` folder, including
  workers and private helpers. Root `tools.py`, `schemas.py`, `platform.py`, and
  `context.py` are thin adapter/shared-platform facades; do not add feature
  implementation files at the root.
- Keep the runtime small; runtime work belongs in the runtime repository and
  platform APIs in the platform backend. Desktop transport and installation
  remain outside the plugin. Local app sharing uses a loopback-only gateway,
  a pinned per-Computer Cloudflare connector, and platform-owned session APIs.
- Keep skills framework-neutral where possible. Hermes loading belongs in
  `plugin.yaml`, `hermes.plugin.json`, and `__init__.py`. Do not add legacy
  framework files.
- Never commit credentials, private backend URLs, tenant data, local machine
  paths, or private instructions. Keep provisioning scripts outside this repo.
- Use simple public language. The README must explain capabilities, limits,
  and the runtime/plugin boundary.

## Read for the task

Read the matching guidance before acting; follow links only when relevant.

| Task | Required guidance |
| --- | --- |
| Start work | Read `CLAUDE.local.md` and `AGENTS.local.md` if present; keep their contents private. |
| Change a capability | [Capability ownership](capabilities/README.md); [public behavior](docs/capabilities.md) for the affected capability. |
| Change or review a packaged skill, tool schema, or adapter registration | [Maintainer skill workflow](.agents/skills/tinyhat-plugin-skill-authoring/SKILL.md). Packaged `skills/` are product instructions; `.agents/skills/` are development workflows. |
| Commit, open a PR, or review one | [Contribution checks and review](CONTRIBUTING.md). |
| Test with a local Hermes installation | [Local development](docs/local-development.md). |
| Change a version, publish, or promote channels | [Release procedure](RELEASING.md), including every live version surface and channel readback. |

Use [README.md](README.md) for the package/skill catalog. Keep release numbers
and capability inventories there and in their manifests, rather than copying
them into this entrypoint.
