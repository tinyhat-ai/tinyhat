---
name: hat-authoring
description: Create and evolve a one-customer Tinyhat Hat through chat, including safe repo files and Computer-local credentials.
---

# Hat authoring

Use this skill when the user asks to create, inspect, or modify a Hat.

## Create

1. Get the hat's human-readable name and the one customer's work email. Ask
   for whichever value is missing. A short key, default Telegram bot username,
   and default Telegram bot display name are optional.
2. Call `tinyhat_hats` with `action="create"`, `name`, `customer_email`, and
   any supplied `key`, `default_bot_username`, and `default_bot_display_name`.
3. Report the returned canonical handle and share URL. Say that the private
   repository was created only when `repository_created` is true. Explain that
   the intended customer can verify their email on that page and create a
   Telegram agent that wears the hat.

Do not ask for account or owner ids; Tinyhat derives them from this Computer.

## List or inspect

- Call `tinyhat_hats` with `action="list"` to list up to 100 hats.
- Call it with `action="get"` and the returned key or canonical handle to
  inspect one hat.

Keep customer emails private unless the user explicitly asks to see the
metadata they supplied.

## Update Hat metadata

Call `tinyhat_hats` with `action="update"`, the current Hat `identifier`, and
one or more of:

- `public_title` for the marketplace title;
- `customer_email` for the intended customer's work email; or
- `new_key` for the final segment of the namespaced canonical handle.

The account namespace is derived from the Computer and cannot be changed by
the model. A handle change renames the existing private repository, preserves
the Hat and its files, keeps former public links resolving to the Hat, and
moves the encrypted Computer-local credential store to the new handle. Report
the new canonical handle and share URL when they change. Keep customer emails
private unless the user explicitly asked to inspect or change that email.

## Delete a Hat

Delete only after the user explicitly asks to permanently remove an exact Hat.
Call `tinyhat_hats` with `action="delete"`, its canonical `identifier`, and
`confirmed=true`. This permanently deletes the private repository and removes
that Hat's Computer-local secret bundle and encryption key without returning a
secret value. Existing agents are not deleted; they simply stop referencing the
removed Hat. Report the returned repository and local-store outcomes honestly.

## Add or update repo content

1. Get the Hat identifier, relative path, and desired non-secret text.
2. Call `tinyhat_hats` with `action="put_file"`.
3. Report whether Tinyhat created or updated the file and name the path.

For a skill, use `skills/<skill-name>/SKILL.md` and include valid skill
frontmatter. A later call to the same path updates it in a new commit, so repo
history remains the undo trail.

Never put an API key, token, password, private key, `.env` file, secret file,
or credential file in the repo. The platform rejects secret-shaped paths and
private-key material, but the skill must avoid sending secret values at all.

## Define and configure Hat credentials

1. Get the Hat identifier plus every meaningful env-style name and short
   purpose. Never ask for any value in chat.
2. For each new or changed field, call `tinyhat_hats` with
   `action="define_credential"`, `identifier`, `credential_name`, and
   `description`. This writes value-blind metadata only.
3. After every field is defined, call `tinyhat_hats` once with
   `action="configure_credentials"` and the Hat `identifier`.
4. Tinyhat sends one expiring **Enter credentials** button. The user sees every
   field on one page. Fields with a Computer-local value are marked as saved
   without revealing that value; leaving one blank preserves it, while an
   entered value replaces only that field. New fields are required. The browser
   encrypts the submitted values with the Hat's Computer-local key. The Computer
   merges them into the Hat's
   local package store under `~/.tinyhat/hats/<owner>/<hat>/secrets.json` for
   its intended customer; plaintext is not stored there. It does not load the
   values into this agent's Hermes environment and does not restart Hermes.

Calling `configure_credentials` again replaces only the values entered in that
submission and preserves saved blank fields. The Hat preview always asks the
assigned Computer to open a fresh encrypted form so its saved-value indicators
are current. Do not claim the save succeeded until Telegram confirms **Hat
credentials saved**.

## List or remove Hat credentials

- Call `tinyhat_hats` with `action="list_credentials"` and the Hat identifier.
  Return names and descriptions only; never infer or claim a value.
- Remove only after the user explicitly asks to remove an exact credential from
  an exact Hat. Then call `tinyhat_hats` with `action="remove_credential"`,
  `credential_name`, and `confirmed=true`. This deletes the local value and its
  value-blind repo metadata. Report `local_value_removed` honestly.
- To recreate a removed credential, define it again, then call
  `configure_credentials` once after all requested names are ready.
