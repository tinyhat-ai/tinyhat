---
name: tinyhat-credit
description: Use when the user asks for their Tinyhat credit balance or recent transactions, asks how much AI model budget this Agent has left or has used, or explicitly asks to add an exact amount of Tinyhat credit to this Agent's AI model budget. Do not use it for automatic, recurring, guessed, or cross-Agent spending.
---

# Tinyhat Credit

Read the authenticated owner's Tinyhat credit summary with `tinyhat_credit`.
Read this Agent's current AI model budget with `tinyhat_model_budget`.
Add credit to this Agent's AI model budget with
`tinyhat_openrouter_credit_allocate`.

New Agents start with about US$5 of model credit. The owner can use their
Tinyhat credit to add more at any time by asking for an exact amount. They can
also choose to connect their ChatGPT/Codex subscription with `/codex_auth`.

## What the tool returns

- `balance_cents`: current available Tinyhat credit in integer cents.
- `currency`: the balance currency, currently `usd`.
- `recent_transactions`: up to ten recent transactions, each with a type,
  signed amount in cents, currency, and timestamp.

Format cents as money in the returned currency. Say `top_up` is "Credit
added." Say `openrouter_allocation` is "Added to model budget." Say
`openrouter_allocation_release` is "Credit returned." Say `computer_usage` is
"Computer usage." For a Computer charge, use its short Computer name, start and
end times, and `hourly_rate_microusd`. Explain the time and applied rate in one
short phrase, such as "2 hr 45 min at $0.10 per hour." If the list is empty,
say there are no transactions yet. Keep the answer short and avoid internal
terms such as ledger, entry, provider key, or idempotency.

## Check the AI model budget

Call `tinyhat_model_budget` when the user asks how much model budget this Agent
has, how much is left, or how much has been used. This is read-only and needs no
confirmation.

- `limit_cents`: the Agent's total AI model budget.
- `remaining_cents`: how much is left, when available.
- `used_cents`: how much has been used, when available.
- `currency` and `checked_at`: the currency and time of the live check.

Format cents as money. Use short labels: **AI model budget**, **Remaining**, and
**Used**. If a value is unavailable, say that briefly instead of estimating it.
Do not mix this with the owner's Tinyhat credit balance.

## Allocate model credit

- The user must explicitly ask to allocate credit and provide the exact amount.
- Convert the exact amount to integer USD cents and call
  `tinyhat_openrouter_credit_allocate` immediately. Their request is the
  authorization. Do not ask “Are you sure?” or require another approval.
- If the amount is missing, ask only for the amount. Never guess, round, or
  choose an amount for the user. The minimum is US$1.00.
- On `allocated`, state the amount, the new AI model budget, and
  the remaining Tinyhat balance.
- On `pending`, explain that Tinyhat is reconciling the provider outcome. Do
  not retry automatically and do not claim the credit was restored.
- On `failed`, say the model budget was not changed and the credit was returned.

## Boundaries

- The platform derives the owner from this Computer's verified assignment.
  Never ask for or invent a user id, account id, Stripe id, or transaction id.
- Only `tinyhat_openrouter_credit_allocate` can change credit, and only for the
  current Computer's assigned Agent after an exact user request. It cannot fund
  another Agent, another user, or a provider key selected by the model.
- If the user wants to add credit, direct them to the Credit control at the top
  of the Configure Mini App opened from their assigned agent bot. Do not claim
  that payment succeeded until the credit balance reflects it.
- Never ask for or expose a provider API key, key hash, management credential,
  user id, Agent id, Computer id, request id, or transaction id.
- Computer charges are automatic. `tinyhat_credit` can explain them, but it
  cannot start, stop, change, refund, or retry a charge.
- Never retry a pending or uncertain allocation. Read `tinyhat_credit` to show
  the latest credit history when the user asks what happened.
