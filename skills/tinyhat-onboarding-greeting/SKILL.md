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
- Keep the greeting natural, specific, and under 60 words.
- Briefly say who you are or how you can help, then end with one simple question
  that makes it easy to start working together.
- Return only the owner-facing greeting text. Do not call a messaging tool; the
  runtime delivers the returned text.

## Boundaries

- Do not repeat setup progress, checklist items, timing, or “Computer is ready”
  language. Tinyhat sends those separately.
- Do not mention this skill, hidden instructions, the model, or internal setup.
- Do not invent capabilities, memories, customer facts, or completed work.
- Do not use this skill for an ordinary hello or any later conversation.
