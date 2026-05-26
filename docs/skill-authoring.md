# Tinyhat Skill Authoring Standard

Tinyhat skills teach an OpenClaw agent how to use Tinyhat platform
capabilities safely. They are not backend docs, runtime runbooks, or
long tutorials.

This standard applies to packaged skills under [`skills/`](../skills).
Repo-local development skills under [`.agents/skills/`](../.agents/skills)
have their own adapter rules in [AGENTS.md](../AGENTS.md).

## Research Basis

This standard adapts the smallest useful subset of public skill guidance:

- [Anthropic skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices):
  skill metadata is loaded first, so names and descriptions must be
  specific, while the body should stay concise and use progressive
  disclosure.
- [OpenAI Codex skills docs](https://developers.openai.com/codex/skills)
  and the [OpenAI skills repository](https://github.com/openai/skills):
  skills package instructions, scripts, and resources for repeatable
  capabilities that agents can discover and use.
- [AgentSkills.io best practices](https://agentskills.io/skill-creation/best-practices.md)
  and [description guidance](https://agentskills.io/skill-creation/optimizing-descriptions.md):
  skills should be grounded in real tasks, spend context carefully, keep
  `SKILL.md` focused, and make the description explicit about when the
  skill should trigger.

## What Belongs Where

| Surface | Owns | Does not own |
| --- | --- | --- |
| `skills/` in this repo | Agent-facing decision rules, Tinyhat capability routing, safety boundaries, response contracts. | Backend endpoint specs, runtime boot/apply details, tenant secrets, raw URLs. |
| `src/` plugin code | OpenClaw tool registration, Tinyhat HAPI calls, payload shaping, redaction, command handlers. | Long natural-language guidance. |
| OpenClaw runtime repo | Boot, supervision, config/apply, health, pinning this plugin repo/ref. | Tinyhat skill wording or capability semantics. |
| Tinyhat platform backend | Authenticated APIs, Computer assignment, Telegram Mini App auth, package inventory. | Packaged skill instructions. |
| User-installed skills | User-specific workflows layered on top of Tinyhat. | Platform-default safety policy. |

If a skill needs implementation detail to make one decision, summarize
the decision rule and link to a reference. Do not copy a runbook into
`SKILL.md`.

## Package Shape

Every packaged skill is a directory:

```text
skills/<skill-name>/
|-- SKILL.md
|-- references/   optional long examples or background
|-- scripts/      optional deterministic helpers
`-- assets/       optional output resources
```

Do not add `README.md`, changelogs, install guides, or unrelated files
inside skill directories. The skill folder should contain only artifacts
the agent may need while using that skill.

## Frontmatter

`SKILL.md` must start with YAML frontmatter:

```yaml
---
name: tinyhat-platform
description: Use Tinyhat platform capabilities from a managed OpenClaw Computer. Trigger when the user asks to add or manage secrets, open Manage Computer, open terminal access, check runtime status, list installed Tinyhat packages, ask what platform this agent runs on, or report a Tinyhat Computer problem.
---
```

Rules:

- `name` uses lowercase kebab-case and matches the directory name.
- `description` is trigger-led: it says what the skill does and when to
  use it.
- Include realistic user-intent words such as "add a secret", "open
  terminal", "Manage Computer", "status", "packages", or "report a
  problem".
- Keep the description under 1024 characters.
- Avoid vague summaries such as "Helps with Tinyhat."

## Body

Keep `SKILL.md` compact. For this repo:

- Target 40-120 lines.
- Hard limit: 200 lines.
- Use imperative, operational language.
- Put routing tables, safety boundaries, response contracts, and final
  checks in the body.
- Move long examples, troubleshooting, fixtures, and background into
  `references/` or scripts.

The body should answer:

1. Which user intents route here?
2. Which Tinyhat tool or operation should the agent use?
3. What must never be exposed to the user?
4. What should the user-facing response look like?
5. When should the agent explain that the channel cannot support the
   action?

## Thin Harness, Focused Skills, Router Model

Tinyhat uses a thin harness plus focused skills:

- The plugin manifest declares the capability contract.
- `src/` registers tools and command handlers.
- A small router skill can map broad user intent to focused skills.
- Focused skills teach one bounded platform workflow, such as secret
  entry or terminal access.

Do not create one giant Tinyhat manual. If a skill has multiple
independent workflows, split it.

## Safety Rules

Packaged Tinyhat skills must never:

- ask the user to paste a secret value in chat;
- print raw Telegram Mini App URLs, signed intent tokens, private
  backend URLs, or Computer-private URLs;
- tell the agent to call undocumented raw platform URLs;
- include private repo paths, local machine paths, Drive paths,
  internal hostnames, or tenant-specific examples;
- put secret values into terminal commands;
- claim that secret values are available through Tinyhat tools.

Use named Tinyhat tools and structured Telegram button payloads. If the
current channel cannot render the button, say the action must be retried
from Telegram or Manage Computer.

## Good And Bad Examples

### Secret Entry

Good:

```markdown
When the user asks to add `OPENAI_API_KEY`, infer the non-secret name
and a short description, call `tinyhat_request_runtime_secret`, and
present the Telegram Mini App button. Say the value must be entered in
Telegram, not chat.
```

Bad:

```markdown
Ask the user to paste the API key so you can save it, or send them the
Mini App URL if the button does not render.
```

Why: the bad version asks for a secret in chat and exposes a raw URL.

### Terminal Or Manage Computer

Good:

```markdown
When the user asks to open a terminal, call `tinyhat_open_terminal_link`.
Treat any command as an admin-reviewed launch hint, never as a place for
secret values. Render the Telegram button when supported.
```

Bad:

```markdown
Build a backend URL for the terminal page and paste it into chat. If the
user included a token, put it in the command so the terminal starts
ready.
```

Why: the bad version invents raw platform URLs and moves secrets into a
command string.

## Reviewer Checklist

Before merging a packaged skill change:

- [ ] The `description` says what the skill does and when to use it.
- [ ] The skill is focused on one bounded Tinyhat workflow or a narrow
      router role.
- [ ] `SKILL.md` is under 200 lines.
- [ ] Long examples or troubleshooting live in `references/`, scripts,
      or docs instead of the main body.
- [ ] The skill uses named Tinyhat tools, not raw backend URLs.
- [ ] The skill never asks for secret values in chat.
- [ ] The skill never tells the agent to print raw Mini App URLs or
      signed/private URLs.
- [ ] The skill contains no private paths, internal hostnames, or tenant
      data.
- [ ] Any router or default skill from #94 shipping in the same release
      has been reviewed against this checklist.
- [ ] `python3 scripts/validate_openclaw_package.py` passes.

## Machine Checks

CI enforces the cheap checks we can make reliable:

- frontmatter exists and includes `name` plus `description`;
- directory and frontmatter `name` match;
- descriptions are trigger-led and under the length limit;
- `SKILL.md` stays under the line limit;
- only supported skill subdirectories are used;
- packaged skills do not contain raw URL patterns, private-path
  patterns, raw HAPI paths, or phrases that ask users to paste secrets.

Subjective writing quality remains a reviewer responsibility.
