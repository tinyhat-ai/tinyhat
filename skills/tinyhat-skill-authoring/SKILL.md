---
name: tinyhat-skill-authoring
description: Create, review, or update portable Agent Skills and SKILL.md files. Use when the user asks to write a skill, add skills to a Hat, revise an existing skill, or improve when a skill should and should not trigger; do not use for ordinary repository files that are not Agent Skills.
---

# Skill authoring

Write focused Agent Skills that trigger predictably and spend context carefully.
For Hat repository skills, use this playbook together with
`tinyhat:hat-authoring` and write files through `tinyhat_hats`.

## Workflow

1. Identify the one user-visible job the skill must perform. From the user's
   request and existing files, write down two or three examples that should
   trigger it and at least two nearby requests that should not. Ask one short
   clarification only when the boundary or required outcome cannot be inferred.
2. If the skill already exists, inspect its full `SKILL.md` and directly linked
   resources before changing it. Preserve useful project-specific rules and
   remove duplicated or stale instructions.
3. Choose the skill name and folder together:
   - use 1-64 lowercase letters, digits, and single hyphens;
   - do not start or end with a hyphen or use consecutive hyphens; and
   - make the frontmatter `name` exactly match the parent folder.
4. Write a frontmatter `description` of at most 1,024 characters. It must say
   what the skill does and when to use it, using phrases a user is likely to
   say. State nearby non-trigger cases when the boundary could be confused
   with another skill. Do not hide trigger guidance only in the body: agents
   see the description before they decide whether to load the body.
5. Write the body in direct, imperative language. Put the main action and
   ordered workflow first. Include only knowledge the agent would not reliably
   know already: project conventions, exact tools, fragile sequences, safety
   boundaries, acceptance checks, and one concise example when it removes
   ambiguity.
6. Keep a normal skill under about 200 lines and 2,000 tokens. Do not exceed
   500 lines or about 5,000 tokens unless the core workflow truly requires it.
   Move long examples, schemas, or domain references into `references/` and
   tell the agent exactly when to read each file. Keep references one level
   deep from `SKILL.md`; use `scripts/` for repeated deterministic operations
   and `assets/` for output templates.
7. Validate the finished skill against the checklist below. For a Hat, commit
   `skills/<skill-name>/SKILL.md` with `tinyhat_hats action="put_file"`; add
   each required reference, script, or asset as its own safe repository file.
   Never place credentials or private keys in a skill or its resources.

## Minimal template

```markdown
---
name: focused-skill-name
description: Perform a specific outcome. Use when the user asks for X or Y; do not use for nearby request Z.
---

# Focused skill name

1. Inspect the required input or current state.
2. Perform the bounded workflow with the named tool.
3. Verify the observable result and report it concisely.

## Guardrails

- Stop and ask when the required target is ambiguous.
- Never expose credentials or claim an unverified result.
```

Adapt the structure to the job; do not add empty sections merely to match the
template.

## Validation checklist

- The directory name and frontmatter `name` match and meet the 64-character
  naming rules.
- The description is non-empty, at most 1,024 characters, and covers both the
  capability and concrete trigger wording.
- The should-trigger examples clearly match the description, while the
  should-not-trigger examples do not.
- The skill does one coherent job and tells the agent what to do before giving
  background.
- The body is comfortably below 500 lines and about 5,000 tokens, or the
  unavoidable reason for exceeding that recommendation is clear.
- Long optional material uses directly linked progressive-disclosure
  resources instead of bloating every activation.
- Instructions, examples, and resources contain no secrets, private platform
  URLs, tenant data, or machine-specific paths.
- Tool names, paths, constraints, and verification steps match the real
  environment.
