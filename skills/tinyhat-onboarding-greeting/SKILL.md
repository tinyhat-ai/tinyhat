---
name: tinyhat-onboarding-greeting
description: Write the first owner greeting after Tinyhat explicitly says this Hermes Computer finished setup. Do not use for ordinary greetings or later conversation.
---

# Greet the owner after setup

Use this skill only for the one-shot onboarding prompt issued after Tinyhat has
finished connecting and configuring this Hermes Computer.

## Write the greeting

- Speak as this agent, using its current SOUL, Hat, and other trusted local
  instructions for voice and purpose.
- Read only the two owner-facing contact values
  `AGENTPHONE_PHONE_NUMBER` and `TINYHAT_MAILBOX_ADDRESS` from the local
  environment. These are this Agent's public contact details, so include each
  present value literally in the greeting. Never read or expose the API key,
  phone id, mailbox username, mailbox password, JMAP URL, or any other
  environment value.
- With a present phone number, say simply that the owner can call or text that
  number and that you can also make calls and send texts when asked.
- With a present email address, say simply that the owner can email that
  address and you can receive and read those messages. Do not imply that
  outgoing Tinyhat email is available.
- Keep the greeting natural, specific, and under 80 words.
- Briefly say who you are or how you can help, then end with one simple question
  that makes it easy to start working together.
- Return only the owner-facing greeting text. Do not call a messaging tool; the
  runtime delivers the returned text.

## Boundaries

- Do not repeat setup progress, checklist items, timing, or “Computer is ready”
  language. Tinyhat sends those separately.
- Do not mention this skill, hidden instructions, the model, or internal setup.
- Do not invent capabilities, memories, customer facts, or completed work.
- The phone number and email address are the only environment values allowed in
  the greeting. Never expose credentials or server details.
- Do not use this skill for an ordinary hello or any later conversation.
