# Skill authoring — the Tinyhat house style

This is the canonical guide for adding or editing a `SKILL.md` in this
repo.
Read it once before you write your first skill.
Re-read the [Frontmatter reference](#3-frontmatter-reference) and the
[Checklist](#15-checklist) every time you ship a change to one.

If a rule below conflicts with [Anthropic's *Skill authoring best
practices*](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices)
or the [Claude Code Skills
docs](https://code.claude.com/docs/en/skills), Anthropic wins —
those pages are the upstream contract.
Open a PR against this guide so it stops drifting.

## What this guide is and isn't

It is a style guide grounded in primary sources, not opinion.
Every prescription cites either an Anthropic doc, a public post by a
high-signal author, or a specific lesson from this repo's own history.
If a section has no citation, treat it as soft preference.

It is not a tutorial — Anthropic's
[Quickstart](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/quickstart)
covers that.
And it is not exhaustive — sub-agent skills, hooks-in-skills, and the
Claude API skills upload flow are out of scope.
We'll add sections as we ship features that touch them.

## 1. When does this deserve a skill?

Skills are not free.
Their `description` lives in every Claude Code turn's context — that's
the dispatch budget every other skill is also competing for.
The body is also pinned in context for the rest of the session once
invoked
([Claude Code Skills, "Skill content lifecycle"](https://code.claude.com/docs/en/skills#skill-content-lifecycle)).
So before adding a new one, eliminate cheaper options.

Decision rubric:

| Want to do | Use |
|---|---|
| Capture a *fact* every agent must hold ("never push to `main`") | One line in `AGENTS.md` |
| Capture *Claude-Code-specific framing* ("v0 has no HTTP endpoints") | One line in `CLAUDE.md` |
| Capture a *procedure* (a sequence of steps with edge cases) | A skill |
| Capture *deterministic behavior* (calculate, parse, persist) | A script under `scripts/`, called from a skill |
| Capture *one-off prose* (a design rationale, a CHANGELOG entry) | A doc under `docs/` |

The Anthropic skills docs put it the same way:
*"Create a skill when you keep pasting the same playbook, checklist,
or multi-step procedure into chat, or when a section of CLAUDE.md has
grown into a procedure rather than a fact."*
([Claude Code Skills, intro](https://code.claude.com/docs/en/skills))

A clean field test from Garry Tan, used in the gstack plugin:

> "If I ask you to do something and it's the kind of thing that will
> need to happen again, you must: do it manually the first time on 3
> to 10 items. Show me the output. If I approve, codify it into a
> skill file. … The test: if I have to ask you for something twice,
> you failed."
> — [garrytan/gbrain ethos doc](https://github.com/garrytan/gbrain/blob/master/docs/ethos/THIN_HARNESS_FAT_SKILLS.md)

If the answer is "I want to make this easier to find," the answer is
probably *not* a skill — it's a clearer paragraph in an existing file.

A worth-knowing dissent: paddo.dev's
[*"Claude Skills: The Controllability Problem"*](https://paddo.dev/blog/claude-skills-controllability-problem/)
argues that skills' opacity (you can't see when they auto-load, can't
override the dispatcher) makes plain slash-commands a better fit for
engineering workflows where you need predictable behavior.
We disagree for skills with side effects (use
`disable-model-invocation: true` instead — see [§3](#3-frontmatter-reference))
but the article is worth reading before you ship a flagship skill.

## 2. Thin harness, fat skills

Tinyhat dogfoods Garry Tan's framing:

> "I call it **thin harness, fat skills**."
> — Garry Tan, ["Thin Harness, Fat Skills"](https://github.com/garrytan/gbrain/blob/master/docs/ethos/THIN_HARNESS_FAT_SKILLS.md)
> (gbrain ethos doc, April 2026)

The principle: files loaded into every agent turn (the harness:
`AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md`, every skill's frontmatter)
stay tight, while procedural detail (the skill: each `SKILL.md` body
plus its `references/`) only loads when invoked.
The economics work because the harness pays a token cost on every
turn; the body pays once per task.

Anthropic's docs make the same point in dispatch terms:

> "At startup, only the metadata (name and description) from all
> Skills is pre-loaded. Claude reads SKILL.md only when the Skill
> becomes relevant, and reads additional files only as needed."
> — [Anthropic, *Skill authoring best practices*, "Concise is key"](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices#concise-is-key)

Concrete consequences in this repo:

- `AGENTS.md` and `CLAUDE.md` link to `.claude/skills/<op>/SKILL.md`
  rather than embedding the procedure.
  See the *Skills index* table in
  [`AGENTS.md`](../AGENTS.md#skills-index--contribution-operations).
- `CLAUDE.md` is 50 lines.
  `update-guidance/SKILL.md` is 86.
  That ratio is the rule, not the exception.

## 3. Frontmatter reference

The frontmatter is the highest-leverage block in the file.
It is what the dispatcher reads and what every other turn pays for.
Get it wrong, the skill never fires.

### Required and recommended fields

| Field | Required? | Use |
|---|---|---|
| `description` | **Recommended** — without it, the dispatcher uses the first paragraph of the body, which is almost always wrong. ([Claude Code Skills, "Frontmatter reference"](https://code.claude.com/docs/en/skills#frontmatter-reference)) | What the skill does + when to use it. Third person. Trigger phrases. See [§4](#4-the-description-is-the-skill). |
| `name` | No — Claude Code falls back to the directory name. The Agent Skills standard requires it (max 64 chars, lowercase + digits + hyphens, no `anthropic`/`claude` reserved words). ([Anthropic, *Skill authoring best practices*, "YAML Frontmatter"](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices#core-principles)) | Set it explicitly when the directory name is ambiguous or when you want to advertise the skill to non-Claude-Code agents. Otherwise omit it and trust the directory. |
| `argument-hint` | No | Document sub-command or argument shape for autocomplete: `[--archive] [--open]`, `status \| on \| off \| where \| clear`. Earns its keep when `$ARGUMENTS` dispatches behavior. |
| `allowed-tools` | No, but **path-scope it when present** | See [§7](#7-permissions-and-allowed-tools) and [issue #18](https://github.com/tinyhat-ai/tinyhat/issues/18). Catch-all globs (`Bash(*)`, bare `Read`, bare `Write`) are an anti-pattern. |
| `disable-model-invocation` | No | `true` for skills with side effects you don't want Claude triggering opportunistically (`/commit`, `/deploy`, `/dev-reset`). The user-typed `/` invocation still works. |

### Trap fields — use sparingly

| Field | Why careful |
|---|---|
| `user-invocable: false` | Hides from the `/` menu. Use only for background-knowledge skills the user shouldn't run as a command. We have none today and probably shouldn't. |
| `model` / `effort` | Overrides the session model for one turn. Almost never the right answer — if a skill needs a stronger model, it's probably under-specified. Document the *what* and let the session model do its job. |
| `paths` | Glob filter that gates auto-invocation by file context. Useful when you write a skill that only applies to `*.tsx` files, etc.; rare for ours. |
| `context: fork` / `agent` | Runs the skill in a forked subagent. Right answer when the skill is doing read-only research and you want to protect the main context. Wrong answer when the skill produces conversation-visible output the rest of the session needs to reference. |
| `disableSkillShellExecution`-bypassing `!\`...\`` blocks | The `!\`cmd\`` syntax preprocesses shell output into the skill body before Claude sees it. Powerful, easy to leak data into the prompt. Limit to read-only commands. |

### Description budget

The skill listing caps each entry's combined `description` +
`when_to_use` text at **1,536 characters**, regardless of session
budget.
Front-load the key use case and trigger phrases — content past 1,536
chars is silently truncated.
([Claude Code Skills, "Frontmatter reference"](https://code.claude.com/docs/en/skills#frontmatter-reference))

If you have many skills installed, the total description budget is the
larger of 1% of the context window or 8,000 chars (env-overridable
with `SLASH_COMMAND_TOOL_CHAR_BUDGET`).
The takeaway: **the first 200 chars of every description are the only
ones you can rely on**.

## 4. The description is the skill

You will spend more time on the `description` than on any other line
of the file.
That's correct — it's what makes Claude *find* your skill.

> "The description is critical for skill selection: Claude uses it to
> choose the right Skill from potentially 100+ available Skills."
> — [Anthropic, *Skill authoring best practices*, "Writing effective descriptions"](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices#writing-effective-descriptions)

> "The description field is not a summary — it's a description of
> when to trigger this skill."
> — Thariq Shihipar (Anthropic), [*Lessons from Building Claude Code*](https://www.linkedin.com/pulse/lessons-from-building-claude-code-how-we-use-skills-thariq-shihipar-iclmc) (2026-03-18)

### Rules

1. **Description = WHEN, not WHAT.**
   The most common authoring mistake is a description that *summarizes*
   the body.
   Jesse Vincent reports a concrete failure:
   *"A description saying 'code review between tasks' caused Claude to
   do ONE review, even though the skill's flowchart clearly showed
   TWO reviews. … The trap: descriptions that summarize workflow
   create a shortcut Claude will take. The skill body becomes
   documentation Claude skips."*
   ([obra/superpowers, "writing-skills"](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md))
   Lead the description with the trigger condition, not the procedure.
2. **Write in third person.** "Generates X." Not "I help you generate
   X." Not "You can use this to generate X."
   Anthropic flags first/second person as a discovery bug, not a
   stylistic preference:
   *"Always write in third person. The description is injected into
   the system prompt, and inconsistent point-of-view can cause
   discovery problems."*
   ([Anthropic, "Writing effective descriptions"](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices#writing-effective-descriptions))
3. **Be directive, not passive.**
   Ivan Seleznov's 650-trial study
   ([*"Why Claude Code Skills Don't Activate"*, Feb 2026](https://medium.com/@ivan.seleznov1/why-claude-code-skills-dont-activate-and-how-to-fix-it-86f679409af1))
   measured passive *vs* directive descriptions across 18 query
   variants × 4 environments × 3 reps:
   passive descriptions activated ~87% of the time bare; directive
   ("ALWAYS invoke this skill when X. Do not Y directly.") hit 100%.
   The Cochran-Mantel-Haenszel odds ratio was 20.6 (p<0.0001) —
   directive wording is roughly **20× more likely to activate**.
   You don't need to shout, but the description should *route*
   ("triggers on X", "use when Y") rather than *narrate* ("does X").
4. **Mine real triggers, don't invent them.** Write down the actual
   sentences a real user has typed for this operation.
   If you haven't watched anyone try, the description is a guess.
   Ship it, then update it the first time the dispatcher misses.
5. **Front-load the key phrase.** The 1,536-char cap can truncate the
   tail; nothing past character ~1,200 should be load-bearing.
   And if you have many skills installed, the dispatch budget can
   silently truncate further — Jesse Vincent's
   ["Skills not triggering?"](https://blog.fsck.com/2025/12/17/claude-code-skills-not-triggering/)
   post-mortem describes Claude refusing to invoke skills it can't see
   in the listing.
   Workaround: `SLASH_COMMAND_TOOL_CHAR_BUDGET=30000` and trim the
   long descriptions in your set.
6. **Avoid vague nouns.** "helper", "utils", "tools", "stuff" — these
   are dispatch-killers
   ([Anthropic, "Naming conventions"](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices#naming-conventions)).

### Shape that works for us

Two valid shapes — pick whichever fits.
The body of the skill is the same; only the framing differs.

**Shape A — verb-first (Tinyhat default).**

```
<verb> <object>. Triggers on "<phrase 1>", "<phrase 2>", … or explicit /<name> invocations.
```

Example from `tinyhat:audit`:

> Audit which Claude Code skills you actually use, which look dormant,
> and what to create next. Produces an agent-authored local
> HTML+markdown report on the data already on disk.
> Triggers on "audit my skills", "run a skill audit", "review my skill
> usage", … or explicit /tinyhat:audit invocations.

**Shape B — trigger-first (Anthropic plugin-dev style).**

```
This skill should be used when the user asks to "<phrase 1>", "<phrase 2>", …, or [activity]. <One-sentence summary.>
```

Example from
[`anthropics/claude-plugins-official` plugin-dev](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/plugin-dev/skills/skill-development/SKILL.md):

> This skill should be used when the user wants to "create a skill",
> "add a skill to plugin", "write a new skill", "improve skill
> description", "organize skill content", or needs guidance on skill
> structure, progressive disclosure, or skill development best
> practices for Claude Code plugins.

Either shape passes the rules above.
Don't mix shapes within one plugin — pick one and stay with it for
predictability.

## 5. One skill = one verb

A skill maps to one operation.
Sub-modes dispatch through `$ARGUMENTS`, **not** through near-identical
sibling skills.

We have a working example: `tinyhat:routine` ships
`status | on | off | where | clear` from a single SKILL.md with a
table of sub-commands.
Five separate skills (`/tinyhat:routine-on`,
`/tinyhat:routine-off`, `/tinyhat:routine-status`, …) would have
quintupled the dispatch surface for no real gain.

When does a sub-command earn promotion to its own skill?

- It has a *different* verb (not just a different argument value).
  `/tinyhat:open` and `/tinyhat:audit` are separate because *opening*
  and *generating* are different operations.
  `/tinyhat:routine on` and `/tinyhat:routine off` are not, because
  they're the same operation with two values.
- Its description has trigger phrases that don't overlap with the
  parent skill's.
  If a user would never say "show my routine" when they mean "turn the
  routine off," they're separate.
- It has different `allowed-tools`.
  If `--archive` needs filesystem write and the bare command doesn't,
  that's a smell — but not yet a split.

When in doubt, dispatch on `$ARGUMENTS`.
Splitting later is cheap; merging later is a rename PR.

## 6. Naming

> "Use consistent naming patterns. Consider using **gerund form**
> (verb + -ing) for Skill names, as this clearly describes the
> activity or capability the Skill provides."
> — [Anthropic, "Naming conventions"](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices#naming-conventions)

> "Use active voice, verb-first … `creating-skills` not
> `skill-creation`. … Gerunds (-ing) work well for processes."
> — [obra/superpowers, "writing-skills"](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md)

Anthropic and the most-installed third-party plugin agree: gerund
form.
We do not strictly follow it — our installed skills are short
imperatives (`audit`, `open`, `commit`, `release`).
The trade-off: gerund names compose better when you have many skills
in the same domain; imperatives read better as slash commands
(`/tinyhat:audit` vs `/tinyhat:auditing`).
Anthropic flags imperatives as an *acceptable alternative* in the same
section — we're inside that envelope, but it's a soft deviation worth
calling out when you copy-paste a Tinyhat skill into your own plugin.

The hard rules:

- Lowercase, digits, hyphens.
  Max 64 chars.
  No `anthropic` or `claude` in the name.
  ([Anthropic, "YAML Frontmatter"](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices#skill-structure))
- Avoid `helper`, `utils`, `tools`, `data`, `documents`, `files` — too
  vague to dispatch on.
- Plugin-namespace ours.
  `/tinyhat:audit` collides only with another plugin called `tinyhat`;
  `/audit` would collide with anyone's `audit`.
  Plugin scope is defense in depth on the dispatcher.

Lesson from this repo's history:
the audit skill went `review` → `skill-audit` → `audit` over three
PRs.
*Short enough for invocation, specific enough that the description
does the dispatch lifting* is the right balance.
A name that tries to dispatch on its own ("skill-audit") double-pays
for what `description` already covers.

If you rename, plan it as one PR per rename — never bundled with
behavior change.
There is no first-class rename support today, so users with the old
name in muscle memory hit a missing-skill error; mitigate by leaving
the old directory in place for one release with a one-line redirect
description (or just accept the break — pre-1.0).

## 7. Permissions and `allowed-tools`

`allowed-tools` pre-approves listed tools while the skill is active.
It does not restrict — every tool remains callable, subject to the
session's permission settings
([Claude Code Skills, "Pre-approve tools for a skill"](https://code.claude.com/docs/en/skills#pre-approve-tools-for-a-skill)).
The benefit is silencing the per-use prompt; the cost is grant
breadth.

Defaults:

- **Path-scope every glob.**
  `Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/foo.py *)` — yes.
  `Bash(python3 *)` — no, that's any-Python.
- **Scope reads and writes too.**
  `Read(${CLAUDE_PLUGIN_DATA}/**)` — yes.
  Bare `Read` — no.
- **`Bash(open *)` is broad** but acceptable for our open-the-HTML
  pattern, since `open` on macOS only opens; tighten to
  `Bash(open ${CLAUDE_PLUGIN_DATA}/latest/report.html)` if your
  invocation only needs one file.
- The temp dir is platform-dependent.
  macOS uses `/var/folders/**`, Linux `/tmp/`, Windows `%TEMP%`.
  Use Python's `tempfile.gettempdir()` rather than hardcoded `/tmp`.

This is tracked as a security debt item in
[issue #18](https://github.com/tinyhat-ai/tinyhat/issues/18); every
new skill must land with path-scoped permissions, and existing skills
will be tightened in a follow-up sweep.

## 8. Path references

Three environment variables matter:

| Variable | What it points to | When to use |
|---|---|---|
| `${CLAUDE_SKILL_DIR}` | The directory containing this `SKILL.md`. For plugin skills, the skill's subdirectory within the plugin — *not* the plugin root. ([Claude Code Skills, "Available string substitutions"](https://code.claude.com/docs/en/skills#available-string-substitutions)) | Reach files bundled inside the skill's own directory: `${CLAUDE_SKILL_DIR}/references/foo.md`, or sibling scripts via `${CLAUDE_SKILL_DIR}/../../scripts/`. |
| `${CLAUDE_PLUGIN_ROOT}` | The plugin's root directory. Empty for repo-scoped skills under `.claude/skills/`. | Reference plugin-level resources from a plugin-scoped skill. Avoid in repo-scoped skills — it'll be empty and break paths. |
| `${CLAUDE_PROJECT_DIR}` | The current project's root directory. | Right answer for repo-scoped skills under `.claude/skills/` that need to find scripts in the project. See `dev-reset/SKILL.md`'s [§Why the path is `${CLAUDE_PROJECT_DIR}`](../.claude/skills/dev-reset/SKILL.md#why-the-path-is-claude_project_dir-not-claude_plugin_root) for the rationale. |

**Repo-scoped vs plugin-scoped** is a real fork:

- `.claude/skills/<name>/SKILL.md` — only loaded when the project is
  open (or installed personally). Used for contribution operations
  (`commit`, `open-pr`, `release`). `${CLAUDE_PLUGIN_ROOT}` is empty
  here.
- `skills/<name>/SKILL.md` — bundled with the plugin and shipped to
  end users. `${CLAUDE_PLUGIN_ROOT}` works; `${CLAUDE_PROJECT_DIR}`
  points at the user's repo, not the plugin.

Don't hardcode `/tmp`, `~/.claude/`, or any path under
`/Users/`/`/home/`.
Use `${CLAUDE_PLUGIN_DATA}` for persisted plugin output, and Python's
`tempfile` for transient files.

## 9. Body structure

> "A skill is a folder, not just a markdown file."
> — Thariq Shihipar (Anthropic), [*Lessons from Building Claude Code*](https://www.linkedin.com/pulse/lessons-from-building-claude-code-how-we-use-skills-thariq-shihipar-iclmc)

The Anthropic-blessed subdirectory taxonomy is **`scripts/`**,
**`references/`**, and **`assets/`** — used identically across the
official plugins.
Tinyhat uses `templates/` instead of `assets/` (HTML/CSS templates
specifically for the report renderer);
treat that as a single intentional deviation, not a precedent.

Every Tinyhat skill follows roughly this shape:

```markdown
---
description: …
argument-hint: …  (only if the skill takes args)
allowed-tools: …  (only if you're pre-approving)
---

# <skill-name> — <one-line value prop>

<1–3 sentence summary. What the skill does. Why running this in Claude
Code is better than reading docs.>

## Related skills

- `/tinyhat:foo` — when to hand off to it.
- `/tinyhat:bar` — when to hand off to it.

## Sub-commands  (only if the skill dispatches on $ARGUMENTS)

| `$ARGUMENTS` | What happens |
|---|---|
| _(empty)_ | Default behavior. |
| `flag` | Variant. |

## Flow  (the actual procedure)

### 1. <step name>

<exactly what to do, with bash blocks where appropriate>

### 2. <step name>

…

## Paths  (optional — only if the skill writes/reads non-obvious files)

- Source: …
- Output: …

## Gotchas  (mandatory — see §11)

- **<the thing that bit us>:** what to do instead.

## Non-negotiables  (optional — only when there are bright lines)

- Never do X.
- Never skip Y.
```

Sections you can drop:
*Related skills* if there are none.
*Sub-commands* if there's no dispatch.
*Paths* if everything is implicit.
*Non-negotiables* if there aren't any.

Sections you can't drop: the value prop and the gotchas.
A skill with neither is a script-with-extra-steps.

## 10. Length budget

Anthropic publishes one number:

> "Keep SKILL.md body under **500 lines** for optimal performance."
> — [Anthropic, *Skill authoring best practices*, "Token budgets"](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices#token-budgets)

Our internal soft ceiling is tighter:

| File | Soft ceiling | Why |
|---|---|---|
| `SKILL.md` body | 200 lines | Most of ours fit. The 500-line ceiling is for skills that *need* to be that long. |
| `references/<topic>.md` | No fixed ceiling | Loaded on-demand; pay only when read. Add a table of contents if it crosses 100 lines. ([Anthropic, "Structure longer reference files with table of contents"](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices#structure-longer-reference-files-with-table-of-contents)) |
| `templates/*` | Whatever the template needs | Not loaded into context — just read by scripts at render time. |

If a skill is approaching 200 lines, ask:

- Is half of this scoped to one mode that fires rarely?
  Move it to `references/`.
- Is half of this *background context* that doesn't need to live in
  the skill's pinned message?
  Move it to a doc.

References should be **one level deep from `SKILL.md`**.
Anthropic specifically calls out nested references as a discovery
hazard:

> "Claude may partially read files when they're referenced from other
> referenced files. … Keep references one level deep from SKILL.md."
> — [Anthropic, "Avoid deeply nested references"](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices#avoid-deeply-nested-references)

## 11. Gotchas are mandatory

Every SKILL.md ships with a `## Gotchas` section.
A real list, not a section stub.
Three or more entries by the time the skill is on its second PR.

This is convergent across the field:

- Anthropic's `plugin-dev/skills/skill-development` ships a
  *"Common Mistakes to Avoid"* section as one of its named H2 blocks.
- Garry Tan's `gbrain/skills/skill-creator`
  [explicitly lists *"Creating a skill without an Anti-Patterns
  section"* as itself an anti-pattern](https://github.com/garrytan/gbrain/blob/master/skills/skill-creator/SKILL.md).
- Jesse Vincent's superpowers plugin makes
  [*"Anti-Patterns"* a standard section](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md).
- Thariq Shihipar (Anthropic): *"The highest-signal content in any
  skill is the Gotchas section."*

Gotchas are the highest-value content in the file because they're the
content that **only comes from running the skill**.
Anthropic's iteration loop says the same thing:

> "Use the Skill in real workflows … observe Claude B's behavior …
> note where it struggles … return to Claude A for improvements."
> — [Anthropic, "Iterating on existing Skills"](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices#develop-skills-iteratively-with-claude)

Examples of real gotchas from Tinyhat skills:

- "**Never fall back to the Python default analysis.** The renderer
  has stubs that work without `analysis.json`, but they read as
  generic." (`audit/SKILL.md`)
- "**Skill inventory varies by OS.** Cowork paths (`~/Library/…`)
  don't exist on Linux or Windows. The scanner skips missing paths
  silently; mention in the coverage note if an expected surface is
  absent." (`audit/SKILL.md`)
- "**`Read` on a `SKILL.md`** is a heuristic signal. The scanner
  drops bare reads as likely false positives." (`audit/SKILL.md`)

A first-PR skill won't have observed gotchas yet — that's fine.
Land it with a placeholder note:

```markdown
## Gotchas

_(populate after first real run — known concerns:)_
- **<concern>:** <hypothesis to verify>.
```

Then update on the second PR with what actually broke.

## 12. No generic fallbacks

The reason to run a skill inside Claude Code is the part the agent
does that a script cannot.
A "generic fallback" — code that produces a plausible answer when the
agent skips its turn — undermines the contract.

Concrete example: `scripts/render_report.py` will compute a Python-
written analysis if `analysis.json` is missing.
The result reads as boilerplate ("you have N skills, M are dormant"),
which is fine for CI smoke tests but wrong for a user-facing run.
Today every Tinyhat skill that *uses* that script has to manually
warn:
*"Never fall back to the Python default analysis."*

That tension is technical debt.
Fix it by either:

- **Removing the fallback entirely** — let the script error out and
  force the agent to write the analysis.
- **Hard-flagging the fallback** at the top of the report
  ("Generated without an agent analysis — re-run inside Claude Code
  for a real audit").

Either way, your skill should not need to recite "don't fall back" in
its prose.
If yours does, file an issue against the underlying script.

## 13. Cross-platform gracefulness

Tinyhat aims to work on macOS, Linux, and Windows.
Skills should:

- **Probe paths, don't crash on absence.**
  Cowork paths (`~/Library/CloudStorage/...`) don't exist on Linux.
  The scanner skips missing paths silently; the coverage note is
  where the user learns what was scanned.
- **Use `${CLAUDE_PLUGIN_DATA}` for persistence**, not
  `~/.claude/...`.
  The plugin-data directory is the supported location; the legacy
  path is supported as a one-shot migration only.
- **Open browsers cross-platform.**
  `open` on macOS, `xdg-open` on Linux, `start` on Windows.
  The `open` and `history` skills include all three; we also fall
  back to `python3 -c 'import webbrowser'` for the unsure case.
- **Use forward slashes in markdown paths.**
  Always.
  ([Anthropic, "Avoid Windows-style paths"](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices#avoid-windows-style-paths))
- **Use `tempfile.gettempdir()` for temp files**, not `/tmp`.

If the skill genuinely can't work on a given OS, say so in the gotcha
list rather than silently producing a worse output.

### Skills fail silently on broken paths

Jenny Ouyang's
[*"Stop Adding New Skills"*](https://buildtolaunch.substack.com/p/claude-skills-not-working-fix)
audit of 214 community skills (April 2026) found 73% scoring < 60/100,
with broken-reference errors as the dominant failure:

> "Claude doesn't throw an error when it reads a broken path. It
> reads the instruction, finds nothing at
> `.claude/skills/seo-convert.md`, and continues as if that line
> wasn't there."

Practical implication: when a skill references
`${CLAUDE_SKILL_DIR}/references/foo.md` or
`${CLAUDE_PLUGIN_ROOT}/scripts/bar.py`, broken paths produce
*looks-fine-but-isn't* runs — the agent reads what it can and
proceeds.
Test the references actually exist on every platform you support, and
add a smoke step in CI that opens every relative-path link from each
skill body.
The lint job in [§17](#17-checklist) covers most of this.

## 14. Testing

Every new skill ships with at least one **skill-dispatch eval** —
*"would Claude pick this skill in response to a representative user
phrase?"*

The detailed test strategy lives in
[issue #24](https://github.com/tinyhat-ai/tinyhat/issues/24); this
section is a short pointer.

Anthropic's evaluation-driven-development advice:

> "Create evaluations BEFORE writing extensive documentation. This
> ensures your Skill solves real problems rather than documenting
> imagined ones."
> — [Anthropic, "Build evaluations first"](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices#evaluation-and-iteration)

Anthropic's `skill-creator` plugin ships a real evaluator
(`run_eval.py`, `aggregate_benchmark.py`, `run_loop.py` —
[skill-creator scripts/](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/skill-creator/skills/skill-creator/scripts))
that runs N-trial variance analysis against a skill.
Worth installing locally before you ship a flagship skill, even if our
own plugin doesn't yet adopt the same harness.

For now (until #24 lands), the minimum bar:

- Three concrete user phrases the skill should pick up.
  Paste them in the description as triggers.
- One run with the lightest model you'd ship to (Haiku 4.5+) to
  confirm the skill still works without an Opus-class to lean on.
- One `claude --plugin-dir "$(pwd)"` smoke test from the repo's
  CONTRIBUTING flow.

CI today runs a packaging-guard and a Python smoke; it does not yet
run skill-dispatch evals.
Don't wait for that to land — write the dispatch trigger phrases now.

### A note on the field disagreement

The community is publicly split on how prescriptive Anthropic's
guidance should be.
Jesse Vincent's superpowers plugin — the most-installed third-party
skills plugin — explicitly states in
[its CONTRIBUTING](https://github.com/obra/superpowers/blob/main/CLAUDE.md):
*"PRs that restructure, reword, or reformat skills to 'comply' with
Anthropic's skills documentation will not be accepted without
extensive eval evidence showing the change improves outcomes."*
Tinyhat's stance: **follow Anthropic's prescriptions by default,
override with eval evidence.**
That's the same posture Vincent demands — he just happens to have
already done the eval work that justifies the deviations in his
plugin.

## 15. Lifecycle

Skills are not write-once.
They have lifespans, and the maintenance question (rename, deprecate,
split, merge) shows up sooner than you'd expect.

### Rename

Today: open a PR that renames the directory and updates every
incoming link.
There's no first-class redirect; users with the old name in muscle
memory hit a missing-skill error.
Mitigations:

- Pre-1.0, just take the break and note it in CHANGELOG.
- If you must, leave the old directory with a one-line `description:`
  redirect ("**Renamed to `<new>`** — invoke that instead.") for one
  release.
- Never rename inside a behavior-change PR.
  One PR, one rename.

This is unsolved at the ecosystem level too — see
[the open question](#16-open-questions).

### Deprecate

If you're sunsetting a skill:

1. Mark the description with `[deprecated, use /<other> instead]`.
2. Open the deletion PR one release later.
3. CHANGELOG entry under `BREAKING CHANGES` if pre-1.0 minor, or `!`
   in the type for post-1.0.

### Split

If a skill's body has crossed the 200-line ceiling and the operations
are independently invokable, split into two skills with
non-overlapping descriptions.

If the operations *aren't* independently invokable — they're sequential
sub-steps — keep one skill and move detail to `references/`.
Splitting sequential sub-steps doubles the dispatch noise.

### Merge

If two skills' descriptions overlap meaningfully and both fire on the
same prompts, the dispatcher will pick non-deterministically.
Merge them.
Argue out which name survives in the merge PR; argue out which
sub-commands they keep.

## 16. Open questions

Fields where Tinyhat hasn't picked an answer yet:

- **Rename support.**
  No first-class redirect today.
  Best practice if known: please open a PR.
- **Eval harness location.**
  Tracked in [#24](https://github.com/tinyhat-ai/tinyhat/issues/24).
- **`disable-model-invocation` policy for our own skills.**
  None of our skills set it, but `commit` / `release` arguably should
  to prevent opportunistic auto-commit.
- **Skill-authoring meta-skill.**
  We'd benefit from a `.claude/skills/write-skill/` that walks an
  agent through this guide before they write a SKILL.md.
  Not yet built; tracked alongside this issue.

Bring receipts when you change one of these.

## 17. Checklist

Before opening a PR that adds or edits a `SKILL.md`, run through:

### Frontmatter
- [ ] `description` is third-person, says **what** + **when**, includes ≥3 trigger phrases.
- [ ] `description` + `when_to_use` combined ≤ 1,536 chars.
- [ ] `name` is omitted *or* matches the directory name (and is ≤64 chars, lowercase + digits + hyphens, no `anthropic`/`claude`).
- [ ] `allowed-tools` is path-scoped (no bare `Bash(*)`, no bare `Read`/`Write`).
- [ ] `disable-model-invocation: true` if the skill has side effects you don't want auto-fired.

### Body
- [ ] One value-prop line directly under the H1.
- [ ] *Related skills* section if any handoffs exist.
- [ ] Sub-command table if `$ARGUMENTS` dispatches behavior.
- [ ] Numbered *Flow* with bash blocks.
- [ ] **`## Gotchas` section present** (placeholder OK on first PR; real entries on the second).
- [ ] Body ≤ 200 lines (Anthropic's hard ceiling is 500).
- [ ] References are one level deep — no `references/foo.md → references/bar.md`.

### Paths
- [ ] No hardcoded `/tmp`, `~/.claude/`, `/Users/`, `/home/`.
- [ ] `${CLAUDE_PLUGIN_DATA}` for persisted output.
- [ ] `${CLAUDE_SKILL_DIR}` for skill-bundled files.
- [ ] `${CLAUDE_PLUGIN_ROOT}` only in plugin-scoped skills.
- [ ] `${CLAUDE_PROJECT_DIR}` only in repo-scoped skills.
- [ ] Forward slashes in every markdown path.

### Discoverability
- [ ] At least one trigger phrase from a *real* user utterance, not a guess.
- [ ] Naming follows §6 (lowercase-hyphen, plugin-namespaced for plugin skills).
- [ ] Skill links to / hands off to its siblings where appropriate.

### Cross-platform
- [ ] Path probes for OS-specific surfaces (Cowork, etc.).
- [ ] Browser-open is `open` / `xdg-open` / `start` (or `webbrowser`).
- [ ] Coverage note is honest about what wasn't scanned.

### Tests
- [ ] At least 3 dispatch phrases written into the description.
- [ ] One smoke run via `claude --plugin-dir "$(pwd)"` (or `--add-dir`
      for repo-scoped) confirms the skill loads and runs.
- [ ] If the skill modifies state, a `--dry-run` or *Confirm before*
      gate is in place.

### Update-guidance
- [ ] If you renamed or moved the skill, you ran
      `grep -rn "<old-skill-name>" docs/ AGENTS.md CLAUDE.md
      .claude/skills/ skills/ .github/`
      and fixed every hit.
- [ ] If this skill changes the meaning of an `AGENTS.md` line, you
      updated `AGENTS.md` in the *same* PR.

If a checkbox doesn't apply, strike it through with a one-word reason
in the PR description rather than silently dropping it.

## 18. Further reading

Primary sources cited above, grouped:

### Anthropic
- [*Skill authoring best practices*](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices) — the canonical prescriptive guide.
- [*Extend Claude with skills*](https://code.claude.com/docs/en/skills) — Claude-Code-specific reference: full frontmatter schema, `${CLAUDE_SKILL_DIR}`, `$ARGUMENTS`, `disable-model-invocation`.
- [*Create plugins*](https://code.claude.com/docs/en/plugins) — plugin manifest, skill namespacing, `${CLAUDE_PLUGIN_ROOT}`.
- [*Equipping agents for the real world with Agent Skills*](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) — engineering deep-dive on progressive disclosure.
- [`anthropics/claude-plugins-official` — `plugin-dev/skills/skill-development`](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/plugin-dev/skills/skill-development/SKILL.md) — Anthropic's own internal "how to write a skill" SKILL.md.
- [`anthropics/claude-plugins-official` — `skill-creator`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/skill-creator/skills/skill-creator) — Anthropic's eval harness for skills.
- Thariq Shihipar (Anthropic), [*Lessons from Building Claude Code: How We Use Skills*](https://www.linkedin.com/pulse/lessons-from-building-claude-code-how-we-use-skills-thariq-shihipar-iclmc).

### Independent practitioners
- Garry Tan, [*Thin Harness, Fat Skills*](https://github.com/garrytan/gbrain/blob/master/docs/ethos/THIN_HARNESS_FAT_SKILLS.md) — gbrain ethos doc.
- Jesse Vincent, [*obra/superpowers* — `writing-skills`](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md) and [*Skills not triggering?*](https://blog.fsck.com/2025/12/17/claude-code-skills-not-triggering/) — TDD-for-skills, the description-budget DoS.
- Ivan Seleznov, [*Why Claude Code Skills Don't Activate (650 trials)*](https://medium.com/@ivan.seleznov1/why-claude-code-skills-dont-activate-and-how-to-fix-it-86f679409af1) — empirical directive-vs-passive study.
- Jenny Ouyang, [*Stop Adding New Skills — Fix the Broken Ones First*](https://buildtolaunch.substack.com/p/claude-skills-not-working-fix) — silent broken-path failures.
- paddo.dev, [*The Controllability Problem*](https://paddo.dev/blog/claude-skills-controllability-problem/) — the contrarian case for slash-commands over skills.

### Cross-ecosystem
- [`agents.md`](https://agents.md/) — the AGENTS.md cross-agent standard (Linux Foundation, Dec 2025).
- [Cursor Rules](https://cursor.com/docs/context/rules) — `.cursor/rules/*.mdc` reference.
- [Windsurf Cascade Memories](https://docs.windsurf.com/windsurf/cascade/memories) — workspace and global rules.
- [Tessl skill registry — *Creating skills*](https://docs.tessl.io/create/creating-skills) — skills package manager.

If you find a strong source not on this list, open a PR adding it.
