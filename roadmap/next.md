# Next

Items queued for after `now.md` clears — roughly in priority order, top first.

---

## Reduce install friction
- **Tracks:** #21
- **Why it's here:** Install friction is the single biggest drop-off before anyone gets
  value. A one-step install unlocks every downstream improvement.
- **Blocks:** #17, #27 (desktop-app walkthroughs are easier to write once install is clean)
- **Blocked by:** —
- **Proposed outcome:** `tinyhat` installs in one command; the canonical example is short
  enough to fit in a tweet.

---

## Fix "all reports" link 404
- **Tracks:** #14
- **Why it's here:** It's a broken core flow. Archived reports linking to a 404 breaks
  the history experience for the only users who've already been running Tinyhat long
  enough to accumulate history.
- **Blocks:** —
- **Blocked by:** —
- **Proposed outcome:** Navigating to any archived report, clicking "all reports," lands
  on the index page — not a 404.

---

## Fix empty report in Cowork sandbox
- **Tracks:** #20
- **Why it's here:** Any user running Tinyhat inside a Cowork sandbox gets a broken
  experience on first run. Fixing it before growing the user base avoids silent churn.
- **Blocks:** —
- **Blocked by:** —
- **Proposed outcome:** `gather_snapshot.py` handles the sandbox path correctly and
  produces a non-empty snapshot.

---

## Summarize the audit in chat
- **Tracks:** #15
- **Why it's here:** Auto-opening an HTML file is jarring. A concise in-chat summary
  gives the user the top insight without leaving the terminal, and sets up the
  actionable terminal output below.
- **Blocks:** #31
- **Blocked by:** —
- **Proposed outcome:** `/tinyhat:audit` prints a 3–5 line summary inline before (or
  instead of) opening the HTML report.

---

## Make the daily audit visible and reliable
- **Tracks:** #16
- **Why it's here:** Users have no feedback that the daily run is happening. Silent
  automation is invisible automation — it erodes trust rather than building it.
- **Blocks:** —
- **Blocked by:** #15 (in-chat summary makes the daily ping meaningful)
- **Proposed outcome:** The daily routine surfaces a clear, brief signal each time it
  runs; users can confirm it's active with one command.

---

## Lower issue-filing friction + add file-issue skill
- **Tracks:** #23
- **Why it's here:** If reporting a bug or requesting a feature requires navigating
  GitHub's UI cold, most friction goes unreported. A skill that walks users through
  filing a well-formed issue from inside Claude Code removes that barrier.
- **Blocks:** —
- **Blocked by:** —
- **Proposed outcome:** `/file-issue` skill exists; users can file a bug or feature
  request from a Claude Code session without leaving the editor.

---

## Tighten commit guidance
- **Tracks:** #22
- **Why it's here:** Commit hygiene is the cheapest form of project legibility — it
  feeds release notes, blame, and bisect for free. The current guidance has gaps that
  agent commits are already exposing.
- **Blocks:** —
- **Blocked by:** —
- **Proposed outcome:** `AGENTS.md` commit section and the `commit` skill reflect
  2026 AI-agent best practice; atomic commits and clear messages are the norm.
