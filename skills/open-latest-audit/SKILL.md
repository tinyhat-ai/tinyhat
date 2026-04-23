---
description: Open the most recent Tinyhat skill-audit report (HTML) in the user's default browser — does NOT regenerate. Triggers on "open my latest skill audit", "show my latest tinyhat report", "open the last tinyhat skill audit", "what did the skill audit say", "open the skill audit report", or explicit /tinyhat:open-latest-audit invocations. If no report exists yet, hand off to /tinyhat:skill-audit to create the first one.
allowed-tools: Bash(open *) Bash(xdg-open *) Bash(start *) Bash(python3 *) Read
---

# tinyhat:open-latest-audit — open the latest skill-audit report as-is

Open `~/.claude/tinyhat/latest/report.html` in the user's default
browser. **Do not regenerate.** That's `/tinyhat:skill-audit`'s job.

## Flow

1. Check whether `~/.claude/tinyhat/latest/report.html` exists.
   - If missing, tell the user "No skill-audit report yet — let me
     create your first one" and hand off to `/tinyhat:skill-audit`.
     Stop here; don't try to open nothing.
2. Open the file with the platform-appropriate command:

```bash
open ~/.claude/tinyhat/latest/report.html        # macOS
xdg-open ~/.claude/tinyhat/latest/report.html    # Linux
start ~/.claude/tinyhat/latest/report.html       # Windows
```

If unsure which OS, use Python's `webbrowser` module (cross-platform):

```bash
python3 -c "import webbrowser, pathlib; webbrowser.open(pathlib.Path('~/.claude/tinyhat/latest/report.html').expanduser().as_uri())"
```

3. In one short sentence, tell the user what they're looking at — the
   date from `~/.claude/tinyhat/latest/run-stamp.txt` is enough:
   *"Opened your most recent skill-audit report from 2026-04-23. Use
   `/tinyhat:skill-audit` to refresh."*

## When the user wants a fresh report

Direct them to `/tinyhat:skill-audit`. Don't regenerate silently — the
agent analysis step is non-trivial and the user may not want to spend
the turns.
