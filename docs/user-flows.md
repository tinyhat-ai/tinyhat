# User flows

Exactly how to use Tinyhat once the plugin is installed. Each flow below covers both the natural-language trigger and the slash command, and tells you what will happen step-by-step.

## Install (one-time)

Inside any Claude Code session:

```text
/plugin marketplace add tinyhat-ai/tinyhat
/plugin install tinyhat@tinyloop
/reload-plugins
```

The first command registers the Tinyloop marketplace (this repo). The second installs the `tinyhat` plugin from it. After install, four skills register under the `tinyhat:` namespace:

If a later `/plugin update tinyhat@tinyloop` looks stale, remove and
reinstall the plugin, then run `/reload-plugins`.

| Slash command | What it does | Regenerates? |
|---|---|:---:|
| `/tinyhat:audit` | Scan → agent writes analysis → render report → summarise in chat with a link | ✓ |
| `/tinyhat:open` | Answer a question about the last audit from JSON, or open the HTML | — |
| `/tinyhat:history` | Open the archive index listing every report on disk | — |
| `/tinyhat:routine` | Manage the daily auto-run (status/on/off/where/clear) | — |

After install, the flows below are what you'll actually do day-to-day.

---

## Flow 1 — Run your first audit

### How to trigger

Any of these work:

- **Slash:** `/tinyhat:audit`
- **Natural language:** *"Audit my skills."* · *"Run a skill audit."* · *"Which skills am I actually using?"* · *"Clean up unused skills."* · *"Which skills should I remove?"* · *"What skills should I create?"*

### What happens

1. The agent runs `gather_snapshot.py`, which reads your local Claude transcripts and skill inventory and writes a structured JSON snapshot to the system temp directory.
2. The agent reads that snapshot and writes its own editorial analysis — headline, what stands out, dormant commentary, recommendations, next-actions, coverage caveats — into a second temp file.
3. The agent runs `render_report.py`, which merges snapshot + analysis into Tinyhat's plugin-data directory (for example `~/.claude/plugins/data/tinyhat-tinyloop/latest/report.{html,md}`) and persists both `snapshot.json` and `analysis.json` next to them.
4. The agent replies in chat with a compact two-line percentage strip, one short headline sentence, and a numbered "pick a next step" menu. **Your browser does not open by default.** Pass `--open` (see below) if you prefer the HTML-first experience, or pick the open-report item from the menu.
5. If you want the richer charts and drill-downs, choose the "open the full HTML report" action or ask for `/tinyhat:open`.

**Typical run time:** 10–30 seconds. Most of it is the agent reasoning over your data, not Python.

### Flags

- **`/tinyhat:audit`** — default. Summarise in chat with a link; no browser.
- **`/tinyhat:audit --open`** — also auto-open `report.html` at the end.
- **`/tinyhat:audit --archive`** — also write a dated copy under `archive/YYYY-MM-DD/`. Implies no auto-open. The adaptive daily run uses this mode.

### The report layout

Above-the-fold (Keep-it-simple mode, default):

- **Two doughnut charts** — skill utilization %, sessions-with-skills %.
- **Next-step menu** — compact numbered actions grounded in this run.
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

By default, `/tinyhat:audit` updates Tinyhat's `latest/` directory under the plugin-data root and overwrites. If you want today's snapshot preserved for comparison later, pass `--archive`:

- `/tinyhat:audit --archive`

That writes an additional `archive/YYYY-MM-DD/` directory under the same plugin-data root (capped at 31 dated dirs — oldest is auto-pruned). The adaptive daily routine always archives.

---

## Flow 2 — Re-open the last report, or ask a question about it

You already ran an audit today (or yesterday). You either want to see it again, or you have a specific question about what it said.

### How to trigger

- **Slash:** `/tinyhat:open`
- **Natural language:**
  - To open the HTML: *"Open my latest skill audit."* · *"Show me the last Tinyhat report."*
  - To ask a question: *"What did the skill audit say?"* · *"Remind me which skills are dormant."* · *"What did you recommend last time?"*

### What happens

The agent reads your message and decides:

- **Specific question** → reads `latest/analysis.json` and `snapshot.json` from Tinyhat's plugin-data directory and answers in chat, citing real numbers and skill names from the saved audit. No browser, no regeneration.
- **Vague / "open it"** → opens `latest/report.html` in your default browser and says one line about when it was generated.

Neither path reruns `gather_snapshot.py`. The persisted JSONs are the source of truth until the next `/tinyhat:audit`.

### If there's no report yet

The agent will tell you and hand off to `/tinyhat:audit` to create the first one. You approve before it runs.

---

## Flow 3 — Browse the history

You have several daily snapshots archived and want to compare weeks, or just navigate between past reports.

### How to trigger

- **Slash:** `/tinyhat:history`
- **Natural language:** *"Show my skill-audit history."* · *"Browse my Tinyhat audits over time."* · *"List all my skill audits."*

### What happens

1. The agent opens Tinyhat's plugin-data `archive/index.html` in your browser.
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

Removes every dated dir under Tinyhat's plugin-data `archive/`. `latest/` and `routine.json` are preserved. Destructive — the agent will confirm first.

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
