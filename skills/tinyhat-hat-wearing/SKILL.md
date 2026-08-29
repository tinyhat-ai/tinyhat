---
name: tinyhat-hat-wearing
description: Install, wear, resume, or finish an accessible Tinyhat Hat on this agent from its handle or URL. Use when a user sends a Hat link or handle, asks this existing agent to use a Hat, or when a newly assigned Hat-enabled Computer needs onboarding. Do not use for creating or editing a Hat; use hat-authoring for that.
---

# Wear a Tinyhat Hat

A Hat adds a private repository of skills and optional Computer-local
credentials to an agent. Hats are free to install. Tinyhat checks whether the
Hat is public or this user is in its private audience, then the Computer
downloads the exact repository with a short-lived, read-only GitHub credential.

## Install on this agent

When the user provides a Hat URL, a full Hat handle, or asks to install it:

1. Call `tinyhat_hats` once with:

   ```json
   {"action":"wear","identifier":"https://tinyhat.ai/account/hats/hat-name"}
   ```

2. If `installation_started=true`, say:

   > I loaded **{hat_title}** and am preparing this Computer from its
   > instructions. This usually takes less than a minute.

3. If credentials are pending, explain only that their encrypted bundle is
   moving automatically from the creator's Computer. The creator already
   authorized this through the Hat audience; never ask either person to approve
   the transfer or paste a value into chat.
4. Do not claim the Hat is ready until `status=active` or Tinyhat sends the
   final `Hat installed` confirmation after the gateway refresh.

If the platform says the Hat is not accessible, explain that it is private and
the creator must add this Tinyhat user. Do not reveal other allowed users.

## Resume after assignment

On the first interaction on a newly assigned Hat-enabled Computer, call:

```json
{"action":"resume_installation"}
```

Use the same progress and completion rules above. A resume is idempotent.

Credential transfer does not require an agent or creator-side chat turn. The
platform dispatches a bounded runtime command to the exact Computer registered
for that Hat. Its plugin encrypts to the consumer key and signs with the Hat's
creator key; the consumer verifies, decrypts, and saves locally. Tinyhat relays
ciphertext only.

## Boundaries

- Never put credential values in a Hat repository.
- Never ask for secrets in Telegram or ordinary chat.
- Never request write access to a consumed Hat repository.
- Never run authoring repository sync for a consumed Hat.
- Accept the canonical handle or the Hat page URL exactly as the user sends it.
- Use `hat-authoring` for create, title/audience/handle edits, files,
  credentials, or deletion of a Hat owned by this user.
