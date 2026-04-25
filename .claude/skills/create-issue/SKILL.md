---
name: create-issue
description: Use when filing a new issue on the tinyhat repo (or another tracker) — covers when to file vs comment, duplicate search, accepted issue types with `skill` first-class, title and body structure, the INVEST rubric Tinyhat adopts as its canonical issue-quality rule, and GitHub / Jira / Linear field mappings. Invoke before opening any new issue.
---

# create-issue — turn rough context into a high-quality work item

Small, focused issues become small, focused PRs. This skill is the
rubric for getting from "there's a problem" to a ticket someone —
agent or human — can finish in one sitting.

## 1. File, update, or comment?

| Situation | Action |
|---|---|
| Same root cause as an open issue | Comment there with new evidence; don't file. |
| Same root cause as a closed issue, regression | Reopen if the trail is short; otherwise file new with `Regresses #N`. |
| Continuation of an in-flight PR's discussion | Comment on the PR. |
| New, distinct concern | File a new issue. |
| Vulnerability or sensitive disclosure | Use [`SECURITY.md`](../../../SECURITY.md), never a public issue. |

## 2. Search for duplicates

```bash
gh issue list --repo tinyhat-ai/tinyhat --state all --search "<keyword>"
gh issue list --repo tinyhat-ai/tinyhat --state all --label <label>
```

Search by symptom, not by your proposed fix — different reporters
describe the same bug differently. Open the top 3 hits even if their
titles look unrelated.

## 3. Choose the type

Use the **title prefix** as the primary signal (the issue templates
default to it), the **GitHub native issue type** where one matches,
and a **label** as the catch-all secondary tag. Verify the current
native types with `gh api /orgs/tinyhat-ai/issue-types`.

| Type | Title prefix | GitHub native | Label | When |
|---|---|---|---|---|
| Bug | `bug:` | Bug | `bug` | Broken behavior, regression. |
| Feature | `feat:` | Feature | `enhancement` | New product behavior. |
| Skill | `feat(skills):` / `chore(skills):` | Feature / Task | `skill` (always) | Create, sharpen, or govern an agent skill. |
| Docs | `docs:` | Task | `documentation` | Documentation or guidance edits. |
| Test | `test:` | Task | — | Test coverage or test infrastructure. |
| Refactor | `refactor:` | Task | — | Internal restructuring, no behavior change. |
| Chore | `chore:` | Task | — | Maintenance that doesn't fit elsewhere. |
| CI / build | `ci:` / `build:` | Task | — | Automation, release plumbing. |
| Security | — | — | — | **Don't file publicly** — use `SECURITY.md`. |

`skill` is first-class: any issue that touches `.claude/skills/`,
proposes a new skill, or governs how skills are written **must** carry
the `skill` label, even when its primary type is `bug` or `docs`. The
org doesn't yet have a native `Skill` issue type — until it does, the
label is the source of truth for skill triage.

## 4. Title

`<type>(<optional scope>): <imperative subject under 72 chars>` —
mirrors the Conventional-Commit format the repo uses for commits. The
subject reads like a headline, not a question:
`bug(report): doughnut charts render off from labeled %`, not
`Charts look weird?`. Search-friendly nouns first.

## 5. Body

Use the matching form in `.github/ISSUE_TEMPLATE/` when one exists.
Whether or not it does, every non-trivial issue carries: **Problem**
(one paragraph, user terms), **Evidence** (traceback / screenshot /
repro / log — no hand-waving), **Proposal** (write `open question`
if unsure), **Acceptance criteria** (section 6), **Out of scope** (so
the implementer doesn't scope-creep), and **Dependencies / links**
(`Blocked by #N`, `Related to #M`, prior art).

Use file paths, function names, and exact commands wherever you can.
Agents handed an issue execute much faster against
`scripts/render_report.py:42` than against "the audit script."

## 6. INVEST — Tinyhat's canonical issue-quality rule

Tinyhat adopts **INVEST** (Bill Wake, 2003 —
https://xp123.com/articles/invest-in-good-stories-and-smart-tasks/) as
the rubric every non-trivial issue is judged against:

- **I**ndependent — workable without first finishing another issue,
  or its `Blocked by` is explicit.
- **N**egotiable — describes the desired outcome, not a frozen
  implementation.
- **V**aluable — the Problem paragraph names who feels the pain.
- **E**stimable — small enough to guess "a day, two days, a week"
  without re-reading three threads.
- **S**mall — bigger than a single PR? Split into `parent` + `subtask`.
- **T**estable — each acceptance criterion is a check the reviewer
  runs (good: "`.claude/skills/create-issue/SKILL.md` exists and is
  under 150 lines"; bad: "skill is well-organized"). Required for
  non-trivial issues; for typo fixes write `trivial` and skip.

If an issue can't pass all six, rewrite or split. **Small + Testable**
is the tightest gate — a one-week issue with criteria like "the audit
feels nicer" fails both.

## 7. Tracker mappings

| Concept | GitHub | Jira | Linear |
|---|---|---|---|
| Type | title prefix + native issue type + label | Issue Type | Type / Label |
| Acceptance | `## Acceptance` in body | "Acceptance Criteria" custom field, else body | "Acceptance" subsection |
| Dependencies | `Blocked by #N` / `Related to #M` in body | Issue links (`is blocked by`, `relates to`) | Sub-issues + relation `is blocked by` |
| Triage queue | `triage` label | Backlog status | `Triage` workflow state |

If the tracker isn't listed, mirror GitHub and ask the maintainer
where the custom fields live.

## 8. Example — a well-formed `skill` issue

```text
Title: feat(skills): add a development skill for creating high-quality issues
Type: Feature   Labels: enhancement, skill

## Problem
Issue format drifts ticket to ticket: some are vague, some bury the
acceptance criteria, some skip the duplicate search.

## Proposal
Add `.claude/skills/create-issue/SKILL.md` covering type taxonomy,
title format, body structure, and one canonical rubric.

## Acceptance
- `.claude/skills/create-issue/SKILL.md` exists, listed in AGENTS.md.
- Defines accepted types and includes `skill` first-class.
- Names INVEST as the canonical rubric and shows how to apply it.
- `.github/ISSUE_TEMPLATE/skill_proposal.yml` matches the skill body.

## Out of scope
Cross-tracker automation (Jira sync, Linear sync).
```

## 9. Non-negotiables

- **Never paste private context** into a public issue: no
  `CLAUDE.local.md` content, no internal Drive paths, no Slack
  threads, no internal hostnames.
- **Never sign an issue as the agent.** Don't append "filed by Claude
  Code" footers; the GitHub author is enough.
- **Never file a vulnerability publicly.** Always use `SECURITY.md`.
- **Never file an issue that fails Small + Testable.** Split it first.
- **Never duplicate-file** without first reading the top 3 search
  hits, even if their titles look unrelated.
