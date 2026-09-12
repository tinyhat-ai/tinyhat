---
name: tinyhat-email-onboarding
description: "Write the first welcome email after a Tinyhat computer and its email channel are ready. Use for the initial email only, not model sign-in, channel setup, or account-upgrade execution."
---

# Welcome your owner

Write a warm, short first email from the agent running on the new Computer.
Return only its body. The channel supplies the subject, progress visual and
reply button, and sends once; do not call a mail or messaging tool.

- Say you are their agent, running on an always-on Tinyhat cloud computer.
- Explain they can reply to this email to work with you right away.
- Briefly name the next steps: choose Telegram or Slack for chatting; connect
  their ChatGPT, Claude Code or Grok model; then optionally enable autonomous
  services with their details, agreement and a monthly spending limit.
- These are next steps, not completed capabilities. Do not start those flows,
  collect identity details, create Stripe accounts, or ask for payment now.
- Ask one easy opening question: what would they like help with first?

Use at most 100 words, short paragraphs, no technical configuration or secret
values. Do not invent their name, occupation, interests, or completed setup.
Use known owner-provided context only. Included model credit is temporary;
do not promise unlimited use or claim a subscription is already connected.
