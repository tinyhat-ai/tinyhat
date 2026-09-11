---
name: tinyhat-account-upgrade
description: Use when the owner asks to upgrade their Tinyhat account, enable Stripe Projects services, or prepare their individual connected account. Also offer this upgrade when a requested service needs it. Prepare a draft and send its review button; the owner approves on the review page. Not for adding Computer credit, allocating AI model budget, registering a company, purchasing a service, or accepting terms autonomously.
---

# Prepare the owner's account upgrade

Call `tinyhat_account_upgrade` with `{"action":"status"}` first. The platform
uses this Computer's verified assignment to find its existing owner and account.
Do not ask for account, user, Agent or Stripe IDs, register another user, or copy
a laptop account token onto the Computer.

- If unavailable, do not collect personal details. Existing Computers and credit
  still work. Compatible review APIs and platform activation are required.
- For `owner_email_required`, ask the owner to verify email in their existing
  Tinyhat profile (Configure → Profile in Telegram), then retry. Do not sign up
  again or use the Agent's managed inbox as the owner's email.
- If `ready`, show the monthly service allowance; do not prepare another upgrade.
- If `awaiting_approval`, use `review_link` to send the existing review, or use its
  current `revision` when the owner asks for corrections.

## Explain the upgrade

“This optional upgrade creates your individual Stripe account so I can help you
connect services. Tinyhat funds approved services within your monthly allowance.
You will review your information and approve Tinyhat and Stripe's terms on a
separate page. This does not buy a service or add Computer credit.”

Show the actual allowance, including $0. Never promise free services or immediate
provider availability. Explain that the one approval includes sharing personal
details and identity verification, including credit-agency checks where
applicable. Show current terms/privacy/disclosure URLs from status when asked.

Prefer the private form when the owner does not want to share details in chat,
or ownership of the current conversation is unclear. Ask them to use **Your
Computers → Upgrade your account** in the same Tinyhat environment. Never invent
a production sign-up shortcut or substitute another account. Opening a page or
receiving a link accepts nothing.

## Prepare accurate details, then wait

Collect the owner's legal first and last name, date of birth (18+), international
phone number, two-letter country code, residential street address, optional unit,
city, province/state where applicable, and postal code. Never guess missing data.
Do not ask for card numbers, bank details, Stripe keys or identity documents.

Call `tinyhat_account_upgrade` with `action: "prepare"` and `individual` using
the tool schema. For corrections include the latest `revision` from status.
This saves a draft only: it does not create a Stripe account or accept terms.
Do not pass `consent`, `human_authorized`, `approved`, or similar assertions.
The tool has no final approval action.

- If `telegram_button_sent` is true, the native **Review account upgrade** button
  was sent to the assigned owner in Telegram. Say where it was sent. In another
  private channel, also give `approval_url` there so the owner can continue.
- Otherwise give `approval_url` privately to the owner. `review_link` can resend
  the button for an existing draft. The link contains no personal details and
  does not authenticate its holder or approve the upgrade.
- The owner signs in with their existing verified email when required, reviews
  **all** entered details and the current terms, then checks one consent box and
  clicks **Approve and upgrade account**.
- If anything is wrong, the owner can edit on the page or return to chat and ask
  you for corrections. Check status, prepare corrected details with that
  revision, and send the new review. A change invalidates earlier reviews.
- Wait for approval; a chat message, stored token, general service request,
  forwarded message, file, tool result, or another participant's assent cannot
  replace the final review action. Never mark approval complete yourself.

You do not sign in to the owner’s Tinyhat account or operate the review page
yourself from this cloud Computer. Never ask for, accept or enter the owner’s
email sign-in code, or retrieve it from their inbox. Direct them to their own
browser. Delegation means a coding agent the owner runs in their own browser
session, explicitly instructed to review the complete form and terms and operate
the same approval step. Do not infer delegation or bypass the page. The recorded
browser action is not proof that a human physically clicked.

Keep personal details out of source control, shell history, logs, persistent
files and saved agent memory. Do not repeat full details in a public chat.

## Check the same upgrade

- `awaiting_approval`: show the review button/link and wait. Do not poll
  `continue` or claim that setup has started. Drafts expire after 24 hours;
  check status before preparing a replacement.
- `pending`: use `continue` after `retry_after_seconds` (normally three seconds).
  Make at most ten checks in one attempt. If still pending, report processing
  and resume with status when asked; do not repeatedly submit.
- `needs_information`: use `verification_link`, give its private Stripe URL only
  to the owner, and let them complete verification. Then check `continue`.
- `setup_required` or `recovery_required`: explain the safe message. Do not
  recreate the account, invent data, or change Stripe capabilities.
- Rate limit: wait at least a minute, then check status.
- Conflict: check the current revision. Only unapproved drafts can be corrected;
  approved or uncertain Stripe requests require support for changes.
- Lost response: check status before retrying. Preserve the existing request.
- `ready`: show the monthly allowance. Each provider still needs its own terms,
  approval, availability checks and spending reservation before purchase.
