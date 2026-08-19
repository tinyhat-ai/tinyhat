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
- Check presence only for the complete local phone bundle:
  `AGENTPHONE_API_KEY`, `AGENTPHONE_PHONE_ID`, and
  `AGENTPHONE_PHONE_NUMBER`. Read and include only the owner-facing phone
  number. Never read or expose the API key or phone id.
- Check presence only for the complete local mailbox bundle:
  `TINYHAT_MAILBOX_ADDRESS`, `TINYHAT_MAILBOX_JMAP_URL`,
  `TINYHAT_MAILBOX_USERNAME`, and `TINYHAT_MAILBOX_PASSWORD`. Read and include
  only the owner-facing email address. Never read or expose the mailbox
  username, mailbox password, or JMAP URL.
- For each complete bundle, include only its owner-facing value named above —
  the phone number or email address — literally. Never include another bundle
  value.
- Only when the complete phone bundle is present, say simply that the owner can
  call or text you at the literal number and that you can also make calls and
  send texts when asked. Do not merely say that you “have a phone.”
- Only when the complete mailbox bundle is present, say simply that the owner
  can email you at the literal address and you can receive and read those
  messages. Do not merely say that you “have email.” Do not imply that outgoing
  Tinyhat email is available.
- When both bundles are complete, prefer one clear sentence such as “You can
  call or text me at <number>, and email me at <address>.” Then explain briefly
  that you can also place calls, send texts, and read incoming email when asked.
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
