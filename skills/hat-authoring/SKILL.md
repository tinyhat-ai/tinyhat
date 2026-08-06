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

## Update the public title

Call `tinyhat_hats` with `action="update"`, the Hat `identifier`, and the new
`public_title`. Report the new title and the unchanged canonical handle.

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

## Add or replace a Hat credential

1. Get the Hat identifier, a meaningful env-style name such as
   `EXA_API_KEY`, and a short purpose.
2. Call `tinyhat_private_secret_handoff` with `name`, `description`, and
   `hat_identifier`. Never ask the user to paste the value in chat.
3. Tinyhat sends an expiring **Enter secret** Mini App button. The browser
   encrypts the value for this Computer. The Computer decrypts it and writes it
   under `~/.tinyhat/hats/<owner>/<hat>/secrets.json`; only the name,
   description, and saved time are recorded in the private Hat repo.

Calling the same flow again with the same name replaces the local value. Do not
claim replacement succeeded until the final Telegram **Secret saved** message.

## List or remove Hat credentials

- Call `tinyhat_hats` with `action="list_credentials"` and the Hat identifier.
  Return names and descriptions only; never infer or claim a value.
- Remove only after the user explicitly asks to remove an exact credential from
  an exact Hat. Then call `tinyhat_hats` with `action="remove_credential"`,
  `credential_name`, and `confirmed=true`. This deletes the local value and its
  value-blind repo metadata. Report `local_value_removed` honestly.
- To recreate a removed credential, run the secure Hat credential flow again.
