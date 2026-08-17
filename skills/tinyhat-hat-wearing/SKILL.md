---
name: tinyhat-hat-wearing
description: Install, wear, resume, or finish a private Tinyhat Hat on this agent from a full handle such as account/hats/hat-name. Use when a user pastes the public-page instruction, asks this existing agent to use a Hat, or when a newly assigned Hat-enabled Computer needs onboarding. Do not use for creating or editing a Hat; use hat-authoring for that.
---

# Wear a Tinyhat Hat

A Hat adds a private repository of skills and optional Computer-local
credentials to one agent. Tinyhat authorizes the verified customer and billing;
the Computer downloads the exact private repository with a short-lived,
read-only GitHub credential.

## Install on this agent

When the user provides a full Hat handle or asks to install it:

1. Call `tinyhat_hats` once with:

   ```json
   {"action":"wear","identifier":"account/hats/hat-name"}
   ```

2. If `payment_required=true`, send the returned checkout URL and tell the user
   to finish checkout. Do not retry, bypass, or claim installation has started.
3. If `installation_started=true`, say:

   > I loaded **{hat_title}** and am preparing this Computer from its
   > instructions. This usually takes less than a minute.

4. If credentials are pending, explain only that their encrypted bundle is
   moving automatically from the creator's Computer. The creator already
   authorized this when they selected the customer; never ask either person to
   approve the transfer or paste a value into chat.
5. Do not claim the Hat is ready until `status=active` or Tinyhat sends the
   final `Hat installed` confirmation after the gateway refresh.

If the platform says the Hat is not accessible, explain that access is limited
to verified users selected by its creator. Do not reveal the intended email.

## Resume after payment or assignment

When the user says payment is complete, or this is the first interaction on a
newly assigned Hat-enabled Computer, call:

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
- Never install from a partial key; require the full namespaced handle.
- Use `hat-authoring` for create, title/customer/handle/pricing edits, files,
  credentials, or deletion of a Hat owned by this user.
