# Tinyhat Roadmap

This folder is the canonical ordering of what Tinyhat is building — not a deadline
list, just a priority-ordered view of the issues queued behind the current work.

## How to read it

| File | Meaning |
|---|---|
| [`now.md`](now.md) | 1–3 items actively being worked on |
| [`next.md`](next.md) | 3–8 items queued after `now` clears |
| [`later.md`](later.md) | Bigger bets and v1+ items not yet scheduled |
| [`considering.md`](considering.md) | Ideas being evaluated but not committed |
| [`rejected.md`](rejected.md) | Proposed items explicitly not pursued (with a short reason — prevents re-proposal churn) |

Every item links to the issue that carries the detail.
The roadmap records *sequence and priority*; the issue records *what and why*.

## How to propose a change

Use the `/propose-roadmap` skill inside Claude Code.
It walks you through the right PR format so the proposal is reviewable and unambiguous.

If you're not using Claude Code, the short version:

1. Open a PR against `roadmap/`. Title: `roadmap: <one-line ask>`.
2. State what you want moved, where, and why (the user pain it addresses).
3. Link the underlying issue(s). A move without an issue is a signal to open one first.
4. One move per PR. *Move #19 from `later.md` to `next.md`* is a PR;
   rewriting `now.md` wholesale is not.
5. Merge = agreement. When a proposal is declined, the maintainer moves it to
   `rejected.md` with the short reason so the argument doesn't loop back.

## Cadence

**Weekly:** re-read the roadmap, graduate items from `next` to `now` when work begins,
move finished items out of `now` (link to the merged PR), pull from `later` into `next`.

**Monthly-ish:** note what moved unexpectedly, what shipped slower than expected.
One-line observations added to this section over time:

<!-- running log — maintainer appends one-liners here -->
