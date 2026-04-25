---
name: history
description: Open the skill-audit history page — a local index of the latest report plus every dated archive snapshot (up to 31), with links to each. Triggers on "show my skill audit history", "browse my tinyhat audits over time", "list all my skill audits", "see previous skill audits", "open the audit archive", "show the tinyhat archive", or explicit /tinyhat:history invocations.
allowed-tools: Bash(open *) Bash(xdg-open *) Bash(start *) Bash(python3 *) Bash(CLAUDE_PLUGIN_DATA=* python3 *) Read
---

# tinyhat:history — browse all skill-audit reports

Open `${CLAUDE_PLUGIN_DATA}/archive/index.html`. That page lists the
latest report plus every dated archive snapshot (up to 31) with
one-click links. Each entry opens its own `report.html`.

If the new plugin-data path is empty but the legacy path
`~/.claude/tinyhat/archive/index.html` exists, use the legacy path for
this browse. The next write-capable Tinyhat command will migrate it.

## Skill-relative script path

`${CLAUDE_SKILL_DIR}` is rendered into the skill content before Claude
runs the Bash block below, so the command keeps pointing at the version
of Tinyhat that loaded this skill.

## Flow

1. Check whether `${CLAUDE_PLUGIN_DATA}/archive/index.html` exists.
   - If it doesn't, check `~/.claude/tinyhat/archive/index.html`.
   - If the new path is missing but `${CLAUDE_PLUGIN_DATA}/latest/report.html` exists,
     regenerate the index without running a new audit:
     ```bash
     python3 "${CLAUDE_SKILL_DIR}/../../scripts/render_report.py" --index-only
     ```
   - If no reports exist at all, tell the user and hand off to
     `/tinyhat:audit` to create the first snapshot.
2. Open the index:

```bash
open "${CLAUDE_PLUGIN_DATA}/archive/index.html"        # macOS
xdg-open "${CLAUDE_PLUGIN_DATA}/archive/index.html"    # Linux
start "${CLAUDE_PLUGIN_DATA}/archive/index.html"       # Windows
```

3. In one sentence, note how many dated snapshots are listed.

## Navigation inside the browser

Every report page has an **all reports →** link in its header that
returns the user here. From this page, each entry opens its own
`report.html`. No server — pure static files.

## When the user wants a fresh report

Direct them to `/tinyhat:audit`. This skill only browses; it
doesn't regenerate.
