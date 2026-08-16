---
name: tinyhat-credit
description: Use when the user asks for their Tinyhat credit balance, remaining credit, or recent credit transactions. Do not use it to add, spend, transfer, refund, or change credit.
---

# Tinyhat Credit

Read the authenticated owner's Tinyhat credit summary with
`tinyhat_credit`.

On OpenClaw, where the native Python adapter tool is not registered, run this
packaged read-only wrapper instead:

```bash
PYTHONPATH="${TINYHAT_RUNTIME_HOME:-$OPENCLAW_STATE_DIR}/extensions" python3 -c 'from tinyhat.tools import credit; print(credit({}))'
```

Use only that exact fallback. It derives the platform endpoint and Computer
identity from the runtime. Do not inspect environment values, config files,
identity files, credential stores, or secret files to assemble the request.

## What the tool returns

- `balance_cents`: current available Tinyhat credit in integer cents.
- `currency`: the balance currency, currently `usd`.
- `recent_transactions`: up to ten newest ledger entries, each with a type,
  signed amount in cents, currency, and timestamp.

Format cents as money in the returned currency. Describe `top_up` as credit
the user added. If the list is empty, say that there are no credit transactions
yet.

## Boundaries

- The platform derives the owner from this Computer's verified assignment.
  Never ask for or invent a user id, account id, Stripe id, or ledger id.
- The tool is read-only. It cannot top up, spend, reserve, transfer, correct,
  refund, or withdraw credit.
- If the user wants to add credit, direct them to the Credit control at the top
  of the Configure Mini App opened from their assigned agent bot. Do not claim
  that payment succeeded until the ledger balance reflects it.
- Do not infer spending from a smaller balance. This first ledger slice records
  additions only; credit consumption is not yet implemented.
