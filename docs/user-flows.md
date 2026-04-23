# User flows

Exactly how to use Tinyhat once the plugin is installed. Each flow below covers both the natural-language trigger and the slash command, and tells you what will happen step-by-step.

## Install (one-time)

Inside any Claude Code session:

```text
/plugin install tinyhat-ai/tinyhat
/reload-plugins
```

That's it. Three skills are now available under the `tinyhat:` namespace:

| Slash command | What it does | Regenerates? |
|---|---|:---:|
| `/tinyhat:audit` | Scan → agent writes analysis → render report → open HTML | ✓ |
| `/tinyhat:open` | Open the latest existing report in your browser | — |
| `/tinyhat:history` | Open the archive index listing every report on disk | — |

After install, the three flows below are what you'll actually do day-to-day.

---

## Flow 1 — Run your first audit

### How to trigger

Any of these work:

- **Slash:** `/tinyhat:audit`
- **Natural language:** *"Audit my skills."* · *"Run a skill audit."* · *"Which skills am I actually using?"* · *"Clean up unused skills."* · *"Which skills should I remove?"* · *"What skills should I create?"*

### What happens

1. The agent runs `gather_snapshot.py`, which reads your local Claude transcripts and skill inventory and writes a structured JSON snapshot to the system temp directory.
2. The agent reads that snapshot and writes its own editorial analysis — headline, what stands out, dormant commentary, recommendations, coverage caveats — into a second temp file.
3. The agent runs `render_report.py`, which merges snapshot + analysis into `~/.claude/tinyhat/latest/report.html` and `report.md`.
4. Your browser opens the HTML. The agent replies in chat with one sentence referencing one observation from the report.

**Typical run time:** 10–30 seconds. Most of it is the agent reasoning over your data, not Python.

### The report layout

Above-the-fold (Keep-it-simple mode, default):

- **Two doughnut charts** — skill utilization %, sessions-with-skills %.
- **Headline** — *"You have N skills installed. You used M of them in the last 30 days."*
- **Stat grid, two groups:**
  - *Skills*: Installed / Active this window / Skill runs detected.
  - *Overall Claude Code usage*: Sessions / Turns / Token activity.
- **Recommended skills** — agent-authored cards, each with a confidence pill and trigger phrases. *Create this skill →* button is "Coming soon" in v0.
- **Cleanup card** — dormant-skill count, clicks over to data-junkie mode.

Data-junkie mode (click the toggle top-right):

- Agent notes (what stands out).
- Dormant skills, origin-grouped with checkboxes and ratio bars.
- Top skills list with ranked runs.
- Session details — filterable by surface and project, sortable by skill runs or recency, times in your local tz.
- All tools used this period — client-side filterable by surface and project.
- Activity patterns — sessions/turns/tokens per day + sessions by surface.
- Coverage note — what was scanned, what was dropped.

### Storing this run as a dated archive

By default, `/tinyhat:audit` updates `~/.claude/tinyhat/latest/` and overwrites. If you want today's snapshot preserved for comparison later, pass `--archive`:

- `/tinyhat:audit --archive`

That writes an additional `~/.claude/tinyhat/archive/YYYY-MM-DD/` directory (capped at 31 dated dirs — oldest is auto-pruned). The adaptive daily routine always archives.

---

## Flow 2 — Re-open the last report without regenerating

You already ran an audit today (or yesterday). You want to look at it again without paying the cost of another run.

### How to trigger

- **Slash:** `/tinyhat:open`
- **Natural language:** *"Open my latest skill audit."* · *"Show me the last Tinyhat report."* · *"What did the skill audit say?"*

### What happens

1. The agent checks `~/.claude/tinyhat/latest/report.html` exists.
2. Opens it in your default browser — no Python runs, no agent reasoning.
3. Replies with one sentence: which date the report is from.

### If there's no report yet

The agent will tell you and hand off to `/tinyhat:audit` to create the first one. You approve before it runs.

---

## Flow 3 — Browse the history

You have several daily snapshots archived and want to compare weeks, or just navigate between past reports.

### How to trigger

- **Slash:** `/tinyhat:history`
- **Natural language:** *"Show my skill-audit history."* · *"Browse my Tinyhat audits over time."* · *"List all my skill audits."*

### What happens

1. The agent opens `~/.claude/tinyhat/archive/index.html` in your browser.
2. The index page lists the **latest** report at the top, then every dated archive snapshot in reverse chronological order. Each entry links to its own `report.html`.
3. Every report has an **all reports →** link in its header that takes you back to this index.

Navigation between reports is entirely in-browser — no Claude involved once the index is open.

---

## Flow 4 — Manage the adaptive daily routine

Tinyhat refreshes at most once per local calendar date, triggered **opportunistically** the first time you use Claude Code each day. No cron, no launchd. Closing your laptop doesn't miss a day.

All routine management lives under `/tinyhat:routine`, which takes one sub-command as its argument.

### Check whether it's on

- **Slash:** `/tinyhat:routine` (or `/tinyhat:routine status`)
- **Natural language:** *"Is Tinyhat's daily run on?"* · *"Check Tinyhat routine."*

Prints `on` or `off` and the date of the last successful run.

### Turn it off / on

- `/tinyhat:routine off` — skill becomes manual-only; no background runs fire.
- `/tinyhat:routine on` — resumes adaptive daily run.

### Print the paths Tinyhat reads and writes

- `/tinyhat:routine where`

Useful when you're debugging or want to tail a file.

### Delete every dated archive

- `/tinyhat:routine clear`

Removes every dated dir under `~/.claude/tinyhat/archive/`. `~/.claude/tinyhat/latest/` and `routine.json` are preserved. Destructive — the agent will confirm first.

---

## Flow 5 — Send feedback

At the bottom of every report you'll see a feedback block:

- **👍 Yes** / **👎 Something's off** — opens your email client with a pre-filled `mailto:tinyhat@tinyloop.co` with the report's date in the subject.
- **Send feedback** — does the same with your optional text note included in the body.

No data is sent over the network by the HTML page itself. Tinyhat is strictly local.

---

## Emotional outcome you should get

- **First run:** *"I finally have a clean picture of which skills on this machine are real."*
- **After a week or two of the archive:** *"I can actually see which parts of my skill surface are alive versus decorative."*

If that doesn't happen, `mailto:tinyhat@tinyloop.co` with a 👎 — specifically what didn't land.
