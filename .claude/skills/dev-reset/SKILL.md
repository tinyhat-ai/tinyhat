---
name: dev-reset
description: INTERNAL DEV ONLY — wipe every byte Tinyhat wrote on this machine so the maintainer can smoke-test a clean first-run install. Repo-scoped, never shipped to end users. Triggers on "reset tinyhat state", "reset my tinyhat for a fresh test", "wipe tinyhat", "pretend I've never installed tinyhat", or explicit `/tinyhat:dev:reset` / `/dev-reset` invocations. Do NOT invoke this on intent like "clean up my skills" (that's `/tinyhat:audit`).
argument-hint: [--full]
allowed-tools: Bash(python3 *)
---

# dev-reset — wipe Tinyhat state for a clean first-run test

**INTERNAL DEV ONLY.** This skill exists solely to let the maintainer
(or an agent on the maintainer's machine) put the local plugin state
back to "never installed" so the next `/plugin install` + `/reload-plugins`
cycle is the real new-user experience. It must never be packaged in the
marketplace manifest — see [issue #55](https://github.com/tinyhat-ai/tinyhat/issues/55).

If the user's intent is anything other than "I'm smoke-testing the
first-run experience", **stop and ask** before running. Everyday
sentences like "clean up my skills" route to `/tinyhat:audit`, not to
this skill.

## Two levels

| `$ARGUMENTS` | What happens |
|---|---|
| _(empty)_ | **Scoped reset.** Wipes plugin data, cache, install manifests, legacy path, temp snapshot/analysis, and tinyhat entries from `installed_plugins.json`. Leaves marketplace registration intact so `/plugin install tinyhat@tinyloop` works immediately. |
| `--full` | **Nuclear reset.** Also removes the `tinyloop` entry from `known_marketplaces.json` and the cloned marketplace source under `~/.claude/plugins/marketplaces/tinyloop/`. Next run has to re-add the marketplace via `/plugin marketplace add tinyhat-ai/tinyhat`. |

## Flow

1. **Preview.** Always run the dry-run first so the user sees the list
   of targets before anything is deleted:

   ```!
   python3 "${CLAUDE_PROJECT_DIR}/scripts/dev_reset.py"
   ```

   For `--full`, append the flag:

   ```!
   python3 "${CLAUDE_PROJECT_DIR}/scripts/dev_reset.py" --full
   ```

2. **Confirm.** Summarize what would be removed in one or two sentences
   and ask the user to confirm. Do not proceed on a plain "go ahead" if
   you've also just asked an unrelated yes/no question.

3. **Commit.** After explicit confirmation, add `--commit`:

   ```!
   python3 "${CLAUDE_PROJECT_DIR}/scripts/dev_reset.py" --commit
   ```

   or, for the nuclear path:

   ```!
   python3 "${CLAUDE_PROJECT_DIR}/scripts/dev_reset.py" --commit --full
   ```

4. **Report.** The script prints `removed …` lines plus a `kept (by
   design):` block. Repeat that in chat so the user sees what stayed
   and why (especially `~/.claude/projects/` — session transcripts).

## Already-clean path

If the script prints `tinyhat dev reset: already clean.`, stop there.
Don't run `--commit`; there's nothing to commit. Tell the user plainly:
their machine is already in the first-run state. If the user asked for
`--full`, the scoped check runs at the same time, so "already clean"
covers both.

## What must not happen

- **Never** touch `~/.claude/projects/`, `~/.claude/rc-dashboard/`, any
  unrelated plugin's data, or files under `~/.claude/plugins/` for
  other plugins. The script already respects this; don't add
  post-processing that widens the blast radius.
- **Never** invoke this skill in automated agent workflows that aren't
  on the maintainer's machine. It's a local dev aid.
- **Never** promote this skill to `skills/` (the packaged plugin path)
  or add it to `.claude-plugin/plugin.json` / `marketplace.json`. CI
  has a guard that fails the build if you do.

## Why the path is `${CLAUDE_PROJECT_DIR}`, not `${CLAUDE_PLUGIN_ROOT}`

This skill is repo-scoped (`.claude/skills/`), not plugin-scoped
(`skills/`). `${CLAUDE_PLUGIN_ROOT}` is empty here because the skill
is not loaded as part of a plugin — it's loaded because Claude Code
reads `.claude/` in the current project. `${CLAUDE_PROJECT_DIR}` points
at the repo root, which is where `scripts/dev_reset.py` lives.

## After the reset

To actually test the first-run flow once state is clean:

```
/plugin marketplace add tinyhat-ai/tinyhat   # only needed after --full
/plugin install tinyhat@tinyloop
/reload-plugins
/tinyhat:audit
```
