---
name: tinyhat-credentials
description: List, find, or remove secure credentials stored only on this Tinyhat Computer. Use when the user asks which credentials exist, wants related credential matches, or asks to delete, remove, replace, or update a saved credential.
---

# Tinyhat Credentials

Use `tinyhat_credentials` for credentials created through Tinyhat's secure
private-secret handoff. Their values exist only on this Computer; Tinyhat keeps
only the name, description, and saved timestamp.

To inspect credentials, call `tinyhat_credentials` with `action="list"`.
Include `query` when the user gives a partial name or purpose. Show only the
returned names and descriptions. Never infer, request, reveal, or claim to read
a credential value.

To remove one:

1. List or search first when the intended credential is not already exact.
2. Select the returned opaque `handoff_id`. If several related matches remain,
   ask the user which name they mean.
3. Call `tinyhat_credentials` once with `action="remove"` and that
   `handoff_id`. An exact `name` is a fallback only when the list has one exact
   current match.
4. Send no extra reply after the removal call. Tinyhat sends an expiring native
   Telegram review button. Its first tap shows final Confirm remove and Cancel
   buttons. Never accept a text confirmation or pass a model-supplied boolean.

After final confirmation, the Tinyhat platform queues a Computer runtime
command. Hermes removes the local env entry, its terminal passthrough alias,
and the loaded process value, then refreshes the gateway. Tinyhat deletes the
value-less credential metadata only after the Computer confirms local removal.

If the button expired, tell the user nothing was deleted and ask them to request
removal again. After successful removal, the same name can be added again with
`tinyhat_private_secret_handoff`; that is the supported replacement/update
flow.
