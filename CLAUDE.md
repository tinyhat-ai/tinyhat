# Claude Code — project context

Cross-agent policy lives in [`AGENTS.md`](AGENTS.md).
Read it before your first commit.
This file only holds Claude-Code-specific context.

If `CLAUDE.local.md` exists next to this file, Claude Code also loads
it.
It is gitignored and internal-only — see
[Local override files](AGENTS.md#local-override-files).

## Product

Tinyhat is the public OpenClaw platform plugin package installed into
Tinyhat-managed Computers.
It teaches the agent which Tinyhat capability to use for credential
entry, Manage Computer, terminal access, status, package inventory, and
support reporting.

The runtime repo boots and supervises OpenClaw.
This repo owns the plugin manifest, capability tools, and default
skills.

## Use The Skills

Contribution procedures live in [`.agents/skills/`](.agents/skills).
When a skill description matches what you are doing, load that skill
instead of copying procedure into this file.
Product-facing skills live under [`skills/`](skills).

## Markdown Conventions

- Markdown only; no MDX.
- ATX headings (`#`), not underline headings.
- Keep eagerly loaded files tight.
- Trailing newline on every file.

## Scope Guard

Do not add private Tinyloop paths, internal URLs, tenant secrets, raw
Mini App URLs, or runtime/bootstrap implementation into this public
plugin package.
