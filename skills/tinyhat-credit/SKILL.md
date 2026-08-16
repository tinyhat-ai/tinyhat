---
name: tinyhat-credit
description: Use when the user asks for their Tinyhat credit balance or recent transactions, or explicitly asks to allocate an exact amount of that credit to this Agent's OpenRouter model budget. Do not use it for automatic, recurring, guessed, or cross-Agent spending.
---

# Tinyhat Credit

Read the authenticated owner's Tinyhat credit summary with `tinyhat_credit`.
Allocate credit to this Agent's OpenRouter model budget with
`tinyhat_openrouter_credit_allocate`.

## What the tool returns

- `balance_cents`: current available Tinyhat credit in integer cents.
- `currency`: the balance currency, currently `usd`.
- `recent_transactions`: up to ten newest ledger entries, each with a type,
  signed amount in cents, currency, and timestamp.

Format cents as money in the returned currency. Describe `top_up` as credit
the user added. Describe `openrouter_allocation` as credit allocated to this
Agent's OpenRouter model budget. Describe `openrouter_allocation_release` as a
failed allocation that Tinyhat restored. If the list is empty, say that there
are no credit transactions yet.

## Allocate model credit

- The user must explicitly ask to allocate credit and provide the exact amount.
- Convert the exact amount to integer USD cents and call
  `tinyhat_openrouter_credit_allocate` immediately. Their request is the
  authorization. Do not ask “Are you sure?” or require another approval.
- If the amount is missing, ask only for the amount. Never guess, round, or
  choose an amount for the user. The minimum is US$1.00.
- On `allocated`, state the amount, the new OpenRouter model-budget limit, and
  the remaining Tinyhat balance.
- On `pending`, explain that Tinyhat is reconciling the provider outcome. Do
  not retry automatically and do not claim the credit was restored.
- On `failed`, explain that the allocation failed and the ledger shows the
  compensating restored credit.

## Boundaries

- The platform derives the owner from this Computer's verified assignment.
  Never ask for or invent a user id, account id, Stripe id, or ledger id.
- Only `tinyhat_openrouter_credit_allocate` can change credit, and only for the
  current Computer's assigned Agent after an exact user request. It cannot fund
  another Agent, another user, or a provider key selected by the model.
- If the user wants to add credit, direct them to the Credit control at the top
  of the Configure Mini App opened from their assigned agent bot. Do not claim
  that payment succeeded until the ledger balance reflects it.
- Never ask for or expose a provider API key, key hash, management credential,
  user id, Agent id, Computer id, request id, or ledger id.
- Never retry a pending or uncertain allocation. Read `tinyhat_credit` to show
  the latest ledger state when the user asks what happened.
