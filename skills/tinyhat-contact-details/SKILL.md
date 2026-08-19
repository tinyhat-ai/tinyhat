---
name: tinyhat-contact-details
description: Use when the user asks for this Agent's Tinyhat-managed phone number or email address, or asks Tinyhat to set up those contact details. Do not use it for the user's personal contact details, another Agent, or sending messages and calls.
---

# Tinyhat Contact Details

Call `tinyhat_contact_details` immediately. It is safe and idempotent: it
returns contact details already assigned to this Agent and creates missing
ones only when the Tinyhat administrator has enabled that type of contact.
It needs no user confirmation and accepts no identity or contact input.

## Explain the result

- `assigned`: show the returned phone number or email address.
- `provisioning`: say the phone number is being prepared and can be checked
  again shortly.
- `disabled`: say this contact type is not enabled yet.
- `not_available`, `not_assigned`, or `unavailable`: say it is not available
  yet.
- `error`: say Tinyhat could not set up the phone number right now.
- If the whole tool call fails, say Tinyhat could not check the contact details
  right now and offer to try again. Do not name the internal error.

Keep the answer short. Say **phone number** and **email address**. Do not use
internal words such as inventory, credential, provider account, assignment
row, or contact record.

The returned phone number and email address belong to this Agent, not to the
owner. Use them as the Agent's public contact details. To check or send mail
after the email address is available, load `tinyhat:tinyhat-mail`. Only claim
that a call or text was placed when a separate phone tool actually confirms
it; knowing the phone number alone does not perform an outbound action.

## Boundaries

- The authenticated Computer chooses its assigned Agent and owner. Never ask
  for or invent a user id, Agent id, Computer id, invitation id, account name,
  API key, desired phone number, or desired email address.
- Never reveal or ask for an AgentPhone API key or an internal reference.
- This tool does not send calls, texts, or email.
