---
name: tinyhat-skill-catalog
description: List Tinyhat plugin skills with qualified names. Use when skill lookup, skill_view, skills_list, or available_skills does not show Tinyhat plugin skills clearly.
---

# Tinyhat Skill Catalog

Use this when Hermes skill discovery is confusing or incomplete.

Call `tinyhat_skill_catalog`. The result lists each Tinyhat skill with:

- `qualified_name`, for example `tinyhat:tinyhat-codex-auth`
- unqualified `aliases`, for example `tinyhat-codex-auth`
- the skill path and purpose

Prefer the qualified name when loading a Tinyhat skill. If
`skill_view(name="tinyhat-codex-auth")` fails, retry with
`skill_view(name="tinyhat:tinyhat-codex-auth")`.

Do not guess at hidden skill names from an error message. Use the catalog
tool, then load the matching qualified skill.
