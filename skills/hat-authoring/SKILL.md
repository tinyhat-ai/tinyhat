---
name: hat-authoring
description: Create a new shareable Tinyhat hat for one customer, list the user's hats, or retrieve one hat's handle and share URL.
---

# Hat authoring

Use this skill when the user asks to create a hat, list their hats, or show
information about one of their hats.

## Create

1. Get the hat's human-readable name and the one customer's work email. Ask
   for whichever value is missing. A short key, default Telegram bot username,
   and default Telegram bot display name are optional.
2. Call `tinyhat_hats` with `action="create"`, `name`, `customer_email`, and
   any supplied `key`, `default_bot_username`, and `default_bot_display_name`.
3. Report the returned canonical handle and share URL. Say that the private
   repository was created only when `repository_created` is true. Explain that
   the intended customer can verify their email on that page and create the
   Telegram agent.

Do not ask for account or owner ids; Tinyhat derives them from this Computer.
Do not create repository files or collect credentials in this milestone. The
public page can create a Telegram agent that wears the hat; its Computer is
prepared later through the normal approval flow.

## List or inspect

- Call `tinyhat_hats` with `action="list"` to list up to 100 hats.
- Call it with `action="get"` and the returned key or canonical handle to
  inspect one hat.

Keep customer emails private unless the user explicitly asks to see the
metadata they supplied.
