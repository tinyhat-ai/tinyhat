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
- Use names that describe the user intent and the capability outcome.
- Keep the body short and operational. Put long examples or references in
  linked docs instead of loading them into every agent run.
- Make the frontmatter `description` specific enough to trigger only for
  the intended user request.
- Define any tool inputs with strict schemas and examples that match real
  user wording.
- Put framework-specific loading in adapter files, not in skill text.
- Do not include private platform URLs, tenant data, tokens, or local
  machine paths.
- Do not ask the user to paste secret values in chat.
- For credentials, require meaningful env-style names. Use
  `EXA_API_KEY`, `GITHUB_TOKEN`, or `STRIPE_SECRET_KEY`; never use
  `TINYHAT_SECRET`, `SECRET`, `API_KEY`, or `TOKEN`.
- For Tinyhat-managed Hermes behavior that should be visible before a
  specific skill loads, use a short `pre_llm_call` context hook and keep
  the longer playbook in a skill.
- Add or update tests when changing a skill's tool contract, naming
  behavior, security wording, or framework adapter registration.

## Skill Checklist

- The skill has one user-visible job.
- The trigger description names the exact user intent that should load it.
- The first steps tell the agent what to do, not why skills exist.
- Examples are concrete and safe to copy.
- Tool schemas reject dangerous or generic inputs.
- User-facing messages are short and put the main action first.
- Security claims match the real platform and runtime behavior.
- README, capabilities docs, tests, and adapter metadata stay in sync.

## Secret Naming Standard

When a skill creates or asks for a credential, choose a name that the
user can recognize later without seeing the value.

| Request | Correct name | Avoid |
| --- | --- | --- |
| "Save my Exa API key" | `EXA_API_KEY` | `TINYHAT_SECRET` |
| "Connect my GitHub token" | `GITHUB_TOKEN` | `TOKEN` |
| "Add a Stripe secret key" | `STRIPE_SECRET_KEY` | `API_KEY` |
| "Save the OpenRouter key" | `OPENROUTER_API_KEY` | `SECRET` |

If the provider or purpose is ambiguous, ask one short clarification
question before creating the handoff.

## Tinyhat Platform Context

Use `pre_llm_call` only for short operating context that should be visible
before a specific Tinyhat skill is loaded. Keep the detailed instructions
inside skills so the plugin stays readable and token efficient.

## Current Skills

`tinyhat-tell-joke` is intentionally small. It proves the plugin is
installed before we add real Tinyhat platform capabilities.

`tinyhat-plugin-version` proves which plugin version Hermes is actually
running. Use it for update tests so we do not confuse admin metadata with
the live plugin code loaded in an agent session.

`tinyhat-private-secret` is the default way to add credentials to Hermes.
It should be triggered before generic `.env` advice whenever a user asks
to add or save an API key, token, password, or credential.

`tinyhat-platform` is the compact operating map for Tinyhat-managed
Hermes agents. It explains secrets, Codex auth commands, usage limit
commands, and the runtime/plugin/platform boundary.
