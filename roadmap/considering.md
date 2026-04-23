# Considering

Ideas actively being evaluated but not yet committed to a time horizon.
Each item needs more signal (user pain, design clarity, or bandwidth) before promotion.

---

## Make the HTML report more minimal
- **Tracks:** #19
- **What's being evaluated:** The current report layout is dense. A minimal redesign
  could improve scannability — but the risk is losing information that power users
  rely on. Need to see the report used more before making a strong call.

---

## Add a screenshot of the report to the README
- **Tracks:** #28
- **What's being evaluated:** A screenshot lowers the "is this worth installing?"
  barrier for new visitors. Blocked only by timing — the report UI should stabilise
  (see #19) before we screenshot it for permanent docs.

---

## Daily audit setup walkthrough (CLI + desktop app)
- **Tracks:** #27
- **What's being evaluated:** Install (#21) and the daily-visible signal (#16) should
  land first. A walkthrough written before those are clean will need a rewrite.

---

## Publish a skill-authoring guide + enforce it per skill
- **Tracks:** #26
- **What's being evaluated:** Valuable for contributors, but enforcement means adding
  CI or review friction. Right-sizing that for a pre-alpha project with one maintainer
  needs thought.

---

## Desktop-app install walkthrough
- **Tracks:** #17
- **What's being evaluated:** Same prerequisite as #27 — install friction should be
  solved first, then walkthroughs are worth writing.

---

## Security audit: least-privilege allowed-tools on every skill
- **Tracks:** #18
- **What's being evaluated:** Important for trust, especially as the user base grows.
  Realistic to do as a one-off sweep, but easy to let drift. May belong in CI rather
  than as a one-time fix.

---

## Define a test strategy for an agent-first skill plugin
- **Tracks:** #24
- **What's being evaluated:** No tests yet in v0. Designing the right test strategy
  for a plugin whose "output" is an agent-authored HTML report is genuinely hard.
  Needs careful thought before any scaffolding goes in.
