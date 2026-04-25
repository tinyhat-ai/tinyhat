---
name: routine
description: Manage the Tinyhat adaptive daily refresh and related housekeeping — show routine status, turn the daily auto-run on or off, print the paths Tinyhat reads and writes, or clear the dated-archive directory. Triggers on "is tinyhat's daily run on", "check tinyhat routine", "turn off tinyhat daily", "disable tinyhat auto-refresh", "enable tinyhat daily", "where does tinyhat save files", "clear tinyhat archive", "delete my tinyhat history", or explicit /tinyhat:routine invocations with an arg.
argument-hint: status | on | off | where | clear
allowed-tools: Bash(python3 *) Bash(CLAUDE_PLUGIN_DATA=* python3 *) Read
---

# tinyhat:routine — manage the daily refresh + diagnostics

All routine-related admin: check whether the adaptive daily auto-run
is on, toggle it, print the paths Tinyhat reads and writes, or wipe
the dated-archive directory. State lives in
`${CLAUDE_PLUGIN_DATA}/routine.json`.

## Sub-commands (dispatch on `$ARGUMENTS`)

| `$ARGUMENTS` | What happens |
|---|---|
| _(empty)_ or `status` | Print routine on/off + last-run date. |
| `on` | Set enabled=true. Adaptive daily run fires on next skill load where it hasn't already fired today. |
| `off` | Set enabled=false. No more background runs. Manual `/tinyhat:audit` still works. |
| `where` | Print the full set of paths Tinyhat reads and writes. |
| `clear` | Delete every dated dir under `archive/`. Keeps `latest/` and `routine.json`. |

## Skill-relative script path

`${CLAUDE_SKILL_DIR}` is rendered into the skill content before Claude
runs the Bash blocks below, so each sub-command keeps calling the
matching bundled `routine.py` for this loaded skill.

### status (default)

```bash
python3 "${CLAUDE_SKILL_DIR}/../../scripts/routine.py" status
```

Prints three lines: `routine: on|off`, `last run: YYYY-MM-DD | (never)`, `home: <path>`. Repeat the output to the user verbatim — no re-phrasing needed.

### on / off

```bash
# turn on:
python3 "${CLAUDE_SKILL_DIR}/../../scripts/routine.py" on

# turn off:
python3 "${CLAUDE_SKILL_DIR}/../../scripts/routine.py" off
```

Both subcommands write `routine.json` atomically and print the new
state. When off, `/tinyhat:audit` continues to work manually — only
the background auto-run is suppressed.

### where

```bash
python3 "${CLAUDE_SKILL_DIR}/../../scripts/routine.py" where
```

Prints the list of sources Tinyhat reads (transcripts, inventory,
optional telemetry) and the paths it writes (under
`${CLAUDE_PLUGIN_DATA}/`). Use this when a user asks where their data is
or wants to tail a file.

### clear

```bash
python3 "${CLAUDE_SKILL_DIR}/../../scripts/routine.py" clear-archive
```

Removes every dated `archive/YYYY-MM-DD/` directory. Does not touch
`latest/` or `routine.json`. **Confirm with the user first** — this
is destructive and they lose their history.

## How the adaptive daily run actually fires

The daily refresh isn't cron-driven. `/tinyhat:audit` checks on every
skill load whether it should fire:

1. Is routine enabled?
2. Has today's snapshot already been written?

If both answers allow it, a background audit fires with `--archive
--no-open`. That's why closing your laptop at midnight doesn't miss a
day — the next Claude Code session that touches Tinyhat re-triggers.

No launchd, no cron, no daemon. Just one check per skill load.

## Gotchas

- `clear` is irreversible. Always confirm before running.
- `where` is read-only — safe to run whenever the user asks "where
  are my Tinyhat files?".
- Toggling `off` does not delete anything; toggling `on` again
  resumes from where you were.
