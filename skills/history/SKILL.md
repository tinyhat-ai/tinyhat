---
description: Open the skill-audit history page — a local index of the latest report plus every dated archive snapshot (up to 31), with links to each. Triggers on "show my skill audit history", "browse my tinyhat audits over time", "list all my skill audits", "see previous skill audits", "open the audit archive", "show the tinyhat archive", or explicit /tinyhat:history invocations.
allowed-tools: Bash(open *) Bash(xdg-open *) Bash(start *) Bash(python3 *) Read
---

# tinyhat:history — browse all skill-audit reports

Open `~/.claude/tinyhat/archive/index.html`. That page lists the
latest report plus every dated archive snapshot (up to 31) with
one-click links. Each entry opens its own `report.html`.

## Load-time: persist the plugin root

`${CLAUDE_PLUGIN_ROOT}` only expands inside `!`-prefixed blocks. The
index-regenerate call below runs via the `Bash` tool where that
variable is empty. Persist it to a known file at load time so the call
can find `render_report.py` no matter which version is installed.

```!
mkdir -p ~/.claude/tinyhat && printf '%s' "${CLAUDE_PLUGIN_ROOT}" > ~/.claude/tinyhat/.plugin-root
```

## Flow

1. Check whether `~/.claude/tinyhat/archive/index.html` exists.
   - If missing but `~/.claude/tinyhat/latest/report.html` exists,
     regenerate the index without running a new audit:
     ```bash
     python3 "$(cat ~/.claude/tinyhat/.plugin-root)/scripts/render_report.py" --index-only
     ```
   - If no reports exist at all, tell the user and hand off to
     `/tinyhat:audit` to create the first snapshot.
2. Open the index:

```bash
open ~/.claude/tinyhat/archive/index.html        # macOS
xdg-open ~/.claude/tinyhat/archive/index.html    # Linux
start ~/.claude/tinyhat/archive/index.html       # Windows
```

3. In one sentence, note how many dated snapshots are listed.

## Navigation inside the browser

Every report page has an **all reports →** link in its header that
returns the user here. From this page, each entry opens its own
`report.html`. No server — pure static files.

## When the user wants a fresh report

Direct them to `/tinyhat:audit`. This skill only browses; it
doesn't regenerate.
