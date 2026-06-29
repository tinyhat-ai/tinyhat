---
name: tinyhat-plugin-skill-authoring
description: Create, modify, or review Tinyhat plugin skills. Use when adding a Tinyhat capability, changing a SKILL.md file, changing plugin tool schemas, updating Hermes adapter metadata, or modifying secret/credential handoff behavior in the tinyhat-ai/tinyhat plugin repo.
---

# Tinyhat Plugin Skill Authoring

Use this skill before changing any file under `skills/`, any plugin tool
schema, or any Hermes adapter registration.

## Standard

- Keep the runtime boring. New user-facing capabilities belong in this
  plugin plus versioned Tinyhat platform APIs, not in runtime code.
- Make one skill do one clear user-visible job.
- Put the exact trigger in frontmatter `description`; keep the body for
  operational instructions.
- Keep `SKILL.md` short. Move long references into `docs/` and link them.
- Register framework-specific details in `plugin.yaml`, `hermes.plugin.json`,
  and `__init__.py`; do not make skill text depend on Hermes-only internals.
- Keep examples concrete and safe to copy.

## Skill Change Checklist

1. Add or update `skills/<skill-name>/SKILL.md`.
2. Update tool schemas in `schemas.py` when the skill calls a tool.
3. Update tool implementation in `tools.py` or a small focused module.
4. Update `hermes.plugin.json`, `plugin.yaml`, and `__init__.py` when a
   new tool, command, or skill becomes part of the public surface.
5. Update `docs/skill-authoring.md`, `docs/capabilities.md`, and
   `README.md` when behavior changes.
6. Add or update unit tests in `test/`.
7. Run:

```bash
python3 scripts/validate_framework_package.py
python3 -m unittest discover -s test -p "*.py"
python3 -m compileall -q .
```

## Secret Skills

Secret and credential skills have stricter requirements:

- Never ask the user to paste secret values in chat.
- Never print, log, snapshot, or include secret values in test fixtures.
- Use the browser-encrypted Mini App handoff for values.
- Choose a meaningful env-style name from the user's wording:
  `EXA_API_KEY`, `OPENROUTER_API_KEY`, `GITHUB_TOKEN`,
  `STRIPE_SECRET_KEY`.
- Reject or clarify generic names such as `TINYHAT_SECRET`, `SECRET`,
  `API_KEY`, `TOKEN`, `PASSWORD`, or `CREDENTIAL`.
- Keep the success message short and explicit that Tinyhat did not store
  the plaintext.

## Review Questions

- Can a user understand what the skill does by reading its name and first
  paragraph?
- Can an agent choose the right tool inputs without guessing?
- Does the tool reject unsafe or ambiguous inputs?
- Are security claims true for both local and GCloud Computers?
- Did tests cover the failure mode that caused this change?
