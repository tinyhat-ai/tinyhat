---
name: tinyhat-account-upgrade
description: Use when the owner asks to upgrade their Tinyhat account, enable Stripe Projects services, or set up their individual connected account. Also offer this upgrade when a requested service needs it. Not for adding Tinyhat credit, allocating AI model budget, creating a company, purchasing a service, or accepting terms without the human's approval.
---

# Upgrade the owner's Tinyhat account

Call `tinyhat_account_upgrade` with `{"action":"status"}` first. The platform
uses this Computer's verified assignment to find its existing owner and account.
Do not ask for account, user, Agent, or Stripe identifiers. This works for
existing customers as well as newly signed-in customers; do not register them
again or ask them to copy a laptop access token onto the Computer.

- If unavailable, say upgrades are not enabled yet. Do not collect personal data
  or consent while activation is off. Existing Computers and credit still work.
- For `owner_email_required`, ask the human to verify their email in their
  existing Tinyhat profile (Configure → Profile in Telegram), then check status
  again. Do not sign up with that email as a shortcut: that could create another
  account. Never use the Agent's managed inbox as the human's email.
- If `ready`, show the monthly service allowance. Do not submit again.

## Explain and get one explicit approval

Explain briefly: “This optional upgrade creates an individual Stripe account so
I can help you connect services. Tinyhat funds approved services within your
monthly allowance. It does not buy a service or add Computer credit.” Show the
actual allowance, including $0. Do not promise services are free or that all
providers are immediately available.

Prefer the private form if the human does not want to provide identity details
in chat: https://computer.tinyhat.ai/tinyhat/account/upgrade . The human signs in
with their verified email. Opening the page accepts nothing.

For an agent-submitted upgrade, show the current `tinyhat_terms_url`,
`stripe_terms_url`, `stripe_privacy_url`, and `stripe_disclosure_url` from status.
Ask for one express approval covering the whole statement:

“I agree to Tinyhat's terms and the Stripe Connected Account Agreement, authorize
sharing my details with Stripe to create and verify my account, and authorize
identity verification, including credit-agency checks where applicable.”

Do not infer this approval from signing in, owning the Computer, a prior token,
or a general request to set up services. An agent's attestation records its claim
of authorization; it is not independent proof of the human's actions. If the
human has already expressly approved these exact current terms, do not ask again.

## Submit accurate individual details

Collect the human's legal first and last name, date of birth (18+), international
phone number, two-letter country code, and residential street address, optional
unit, city, state/province where applicable, and postal code. Never guess. Do not
ask for a card number, bank details, Stripe key, or identity document in chat.
If Stripe needs documents, send its verification link to the human.

Call `tinyhat_account_upgrade` with `action: "submit"`, `individual`, and
`consent`. The object shapes are in the tool schema. After the human approves,
use the `terms_version` you presented and set all five consent booleans to true:
`tinyhat_terms_accepted`, `stripe_terms_accepted`,
`personal_data_sharing_accepted`, `identity_verification_accepted`, and
`human_authorized`. These fields record the points covered by one approval;
they do not require five separate confirmations.

Keep personal details out of source control, logs, shell history, saved agent
memory, and persistent files. Do not echo the completed details back in a public
chat. The tool uses the Computer identity internally and returns no platform card
or general account token.

## Finish the same upgrade

- `pending`: call with `action: "continue"` after `retry_after_seconds` (normally
  three seconds). Continue until the state changes.
- `needs_information`: call with `action: "verification_link"` and give the
  returned private Stripe URL only to the human. They complete verification.
  Check again with `continue`; returning from Stripe is not proof of readiness.
- `setup_required` or `recovery_required`: explain the returned message. Do not
  substitute payout or merchant accounts, invent data, or recreate the account.
- An uncertain submission: check `status` first, then retry only the identical
  submission if necessary. Changed personal details require Tinyhat support.
- `ready`: state the monthly allowance. Provider-specific terms, approvals,
  availability, and spending reservations are still required before purchases.

For API access from a coding agent on a laptop, follow the owner email-code flow
in https://tinyhat.ai/agents.md . Computer identity is accepted only by the
assignment-scoped Computer upgrade APIs; it is not a general user session.
