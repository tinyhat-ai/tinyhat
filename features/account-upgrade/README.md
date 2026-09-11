# Reviewed individual account upgrade

The assigned Computer prepares an encrypted owner-bound draft. The tool sends a
Telegram review button when available and always returns its review URL. The
button uses Telegram sign-in when the platform supplies `mini_app_url`. A
missing or null Mini App URL falls back to the standalone review page, which may
require the owner's existing verified email sign-in. The owner reviews all details
and the terms and approves using one checkbox and the final approval button. Changes
invalidate earlier reviews. The tool has no consent or final approval action.

This keeps existing owner accounts and Computer credentials; it does not sign up
another user, grant spending credit, or purchase a service. Compatible platform
review APIs must deploy before this plugin is released. No runtime or channel
change is included.

Verification covers allowed actions, revision handling, removal of attested
consent, safe review URLs, Telegram message/button generation, the review URL
kept after delivery, transport errors, owner identity and package registration.
Real Telegram and coding-agent review evidence is recorded in the PR.
