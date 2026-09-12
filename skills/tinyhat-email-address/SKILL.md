---
name: tinyhat-email-address
description: "Check or change this agent's Tinyhat email address when the owner asks \"what is your email?\", \"change your email\", or \"rename your inbox\". Not for changing the owner's sign-in email or accessing their Gmail."
---

# Change your Tinyhat email

1. Call `tinyhat_email_address` with `action: "status"`.
2. For a change, ask for the desired name before `@`, then call `action:
   "prepare"` and `local_part` with that name.
3. Show both complete addresses and the returned notice. Say clearly:
   **Your old address will stop receiving mail 24 hours after you confirm.
   Update anything using it before that deadline. Your existing messages stay.**
4. Wait for the owner's explicit confirmation of this change and its expiry.
   A request to rename alone does not acknowledge the 24-hour retirement.
5. Call `action: "confirm"` with the preparation's `confirmation_token` and
   `acknowledge_old_address_expires_in_24_hours: true`. Never make up a token or confirmation.
6. Report the returned new address and exact old-address expiry. If the status
   is still `renaming`, check again before saying the new address is active.
7. If a mail client was configured, use `tinyhat:tinyhat-mail-client`: fully close
   and reopen desktop Mail after runtime settings update, and update any external
   client's username/address through a new private settings export. Preserve its
   messages and drafts.

The platform allows three confirmed changes per rolling 24 hours, shared
across the owner's agents. Previews expire in 15 minutes and do not reserve
names. For a conflict, expired preview, or daily limit, explain the returned
status and prepare again only when appropriate. Email can be sent only to the
verified owner; changing the agent's address does not change that recipient.
