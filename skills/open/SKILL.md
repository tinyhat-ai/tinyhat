---
description: Open the most recent Tinyhat skill-audit report (HTML) in the user's default browser, or answer a specific question about it from the persisted JSON — does NOT regenerate. Triggers on "open my latest skill audit", "show my latest tinyhat report", "open the last skill audit", "what did the skill audit say", "remind me what the audit said about X", "which skills are dormant", "open the skill audit report", "open tinyhat", or explicit /tinyhat:open invocations. If no report exists yet, hand off to /tinyhat:audit to create the first one.
allowed-tools: Bash(open *) Bash(xdg-open *) Bash(start *) Bash(python3 *) Read
---

# tinyhat:open — read from or open the latest audit

Two jobs, decided by what the user actually asked for:

1. **Answer a specific question about the last audit** — read the
   persisted JSONs at `~/.claude/tinyhat/latest/{snapshot,analysis}.json`
   and reply in chat. No browser.
2. **Open the HTML report as-is** — when the user just wants to see it.

**Never regenerate.** That's `/tinyhat:audit`'s job. The agent analysis
step is non-trivial and the user may not want to spend the turns.

## Decide which job you're doing

Read the user's message. If it contains a specific question —
*"what did the audit say about dormant skills?"*, *"which skills did I
use this week?"*, *"remind me what you recommended"* — it's **job 1**:
answer from JSON. The phrasing is asking for a fact, not a viewing
experience.

If the message is vague-open — *"open tinyhat"*, *"show me the
report"*, *"/tinyhat:open"* — it's **job 2**: open the HTML.

When in doubt, prefer job 1. Reading from JSON and answering inline
keeps the user's attention in the terminal; opening a browser tab
moves it away.

## Job 1 — answer from JSON

1. Check `~/.claude/tinyhat/latest/analysis.json` and
   `~/.claude/tinyhat/latest/snapshot.json` both exist.
   - If missing, say "I don't have a saved audit to read from — let me
     run a fresh one" and hand off to `/tinyhat:audit`. Stop.
2. Read one or both JSONs with the Read tool. Prefer `analysis.json`
   for editorial questions (*"what stood out?"*, *"what did you
   recommend?"*) and `snapshot.json` for factual questions (*"which
   skills did I use?"*, *"how many sessions?"*).
3. Answer in chat. Cite specific numbers/skills from the JSON. Name
   the date the audit ran (`run-stamp.txt`). End with one line the
   user can act on — usually a `file://` link to the full HTML if
   they want more detail.

### Shape of a good answer

> From your 2026-04-23 audit: 107 of 121 installed skills were dormant
> — the bulk (82) are plugin-bundled skills that came with
> marketplaces you installed. Open the full report at
> `file:///Users/you/.claude/tinyhat/latest/report.html` to see them
> grouped by origin.

### Rules

- **Never re-run `gather_snapshot.py`.** The JSONs on disk are the
  source of truth for this skill.
- **Use literal numbers from the JSON.** Don't paraphrase counts.
- **Only reference skills that appear in `snapshot.inventory`.**
- If the question can't be answered from the JSON (e.g. *"what would
  you recommend next week?"*), say so and suggest running a fresh
  audit.

## Job 2 — open the HTML

1. Check whether `~/.claude/tinyhat/latest/report.html` exists.
   - If missing, tell the user "No skill-audit report yet — let me
     create your first one" and hand off to `/tinyhat:audit`.
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
   `/tinyhat:audit` to refresh."*
