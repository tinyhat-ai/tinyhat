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
- Lead with what this Agent is here to help with. The first sentence must
  introduce its broader purpose, personality, or useful work without mentioning
  phone, text messages, or email.
- Ground that introduction in the Agent's trusted local instructions and
  available capabilities. Keep it broad and useful: for example research,
  planning, writing, analysis, automation, or the Agent's Hat-specific work.
  Do not invent a capability merely to make the greeting sound impressive.
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
- Only after the broader introduction, mention each complete contact bundle as
  an optional way the owner can reach this Agent. Keep all contact details to
  one short sentence.
- Only when the complete phone bundle is present, include the literal number in
  simple wording such as “You can also call or text me at <number>.”
- Only when the complete mailbox bundle is present, include the literal address
  in simple wording such as “You can also email me at <address>.” Do not imply
  that outgoing Tinyhat email is available.
- When both bundles are complete, prefer one sentence such as “You can also
  reach me by call or text at <number>, or by email at <address>.”
- Do not turn the greeting into a list of phone, text, or email operations.
  Those are contact options, not the Agent's main purpose; explain operational
  details later only when the owner asks to use them.
- Keep the greeting natural, specific, and under 80 words.
- End with one simple question that makes it easy to start useful work together.
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
