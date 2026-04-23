# Later

Bigger bets and v1+ items — real and valuable, but not the next thing to start.
Nothing here should be lost; it just isn't scheduled yet.

---

## Actionable terminal output — let the user pick a next step
- **Tracks:** #31
- **Why it's here:** Once the in-chat summary (#15) exists, the natural evolution is
  making each finding interactive — numbered options, one keystroke to act on the
  top suggestion.
- **Blocks:** —
- **Blocked by:** #15
- **Proposed outcome:** After the summary, the agent presents numbered follow-ups
  (e.g. "1 — create skill for pattern X · 2 — retire dormant skill Y") and acts
  on the user's choice without extra prompting.

---

## Detect mistake patterns + recommend skill creation or sharpening
- **Tracks:** #30
- **Why it's here:** Transcript analysis that spots repeated corrections or
  anti-patterns is a step toward proactive skill suggestions — not just "here's what
  you used" but "here's what you keep getting wrong."
- **Blocks:** —
- **Blocked by:** #31 (actionable output makes mistake-pattern findings useful)
- **Proposed outcome:** Tinyhat detects clusters of similar corrections or recoveries
  in transcripts and surfaces them as skill-creation or skill-sharpening suggestions.

---

## Team telemetry — skill usage across a team
- **Tracks:** #29
- **Why it's here:** The single-machine model tops out quickly for teams. Aggregated
  skill usage and suggestions across contributors is the v1 unlock that makes Tinyhat
  valuable in an org context, not just for a solo developer.
- **Blocks:** —
- **Blocked by:** v0 feature set should be stable before adding multi-machine scope
- **Proposed outcome:** A team-level report showing which skills are used (and missing)
  across multiple machines — no server required, opt-in telemetry, privacy-respecting.
