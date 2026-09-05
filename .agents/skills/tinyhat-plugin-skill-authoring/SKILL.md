---
name: tinyhat-plugin-skill-authoring
description: Create, modify, or review Tinyhat plugin skills. Use when adding a Tinyhat capability, changing a SKILL.md file, changing plugin tool schemas, updating Hermes adapter metadata, or modifying secret/credential handoff behavior in the tinyhat-ai/tinyhat plugin repo.
---

# Tinyhat Plugin Skill Authoring

Use this development workflow before changing or reviewing `skills/`, plugin
tool schemas, or Hermes adapter registrations. Read the affected capability in
`capabilities/README.md` and the packaged-skill contract in
`docs/skill-authoring.md` before editing.

## Standard

- Make one skill do one clear user-visible job.
- Put the exact trigger in frontmatter `description`; keep the body for
  operational instructions.
- Include concrete should-trigger wording and nearby non-trigger boundaries in
  the description when another skill could plausibly match.
- Keep decision-relevant steps and safety constraints in the skill; move
  extended examples or reference material to directly linked resources with
  explicit read conditions. Do not remove needed detail just to shorten a file.
- Register framework-specific details in `plugin.yaml`, `hermes.plugin.json`,
  and `__init__.py`; do not make skill text depend on Hermes-only internals.
- Keep examples concrete and safe to copy.

## Skill Change Checklist

1. Add or update `skills/<skill-name>/SKILL.md`.
   For general user-authored skills, keep
   `skills/tinyhat-skill-authoring/SKILL.md` aligned with the open Agent Skills
   naming, description, and progressive-disclosure rules.
2. Update tool schemas in `schemas.py`. Put product implementation in the
   owning `capabilities/` folder and update the root `tools.py` facade as needed.
3. Update `hermes.plugin.json`, `plugin.yaml`, and `__init__.py` when a
   new tool, command, or skill becomes part of the public surface.
4. Update `docs/skill-authoring.md`, `docs/capabilities.md`, and
   `README.md` when behavior changes.
5. Add or update unit tests in `test/` for changed behavior, including unsafe
   inputs and the failure mode being fixed.
6. Run the checks in `CONTRIBUTING.md` before committing or opening the PR.

## Secret Skills

When changing secret or credential behavior, apply these requirements before
editing:

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
