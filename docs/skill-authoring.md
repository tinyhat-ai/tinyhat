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
- Use names that describe the user intent.
- Keep the body short and operational.
- Put framework-specific loading in adapter files, not in skill text.
- Do not include private platform URLs, tenant data, tokens, or local
  machine paths.
- Do not ask the user to paste secret values in chat.

## Current Skills

`tinyhat-tell-joke` is intentionally small. It proves the plugin is
installed before we add real Tinyhat platform capabilities.

`tinyhat-plugin-version` proves which plugin version Hermes is actually
running. Use it for update tests so we do not confuse admin metadata with
the live plugin code loaded in an agent session.
