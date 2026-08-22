# Browser-to-Computer E2EE verification

Captured during the live development E2E on 2026-08-22 with the assigned
Tinyhat test Computer and Telegram owner account. Share URLs, numeric access
codes, Telegram authorization data, and unrelated chats are intentionally
omitted.

- `telegram-loading-only.png`: the Mini App starts with only the loading
  spinner; there is no explanatory or verification text.
- `telegram-decrypted-app.png`: the authenticated owner sees the Computer's
  decrypted local app inside Telegram without entering a code.
- `telegram-encrypted-navigation.png`: a relative same-origin link still
  decrypts after the service worker has been idle.
- `browser-code-gate.png`: the same kind of link opened outside Telegram asks
  for the four-digit numeric access code.

The corresponding browser run also proved that reopening the canonical share
URL retained authorization, kept the session path and encryption fingerprint,
and did not retain Telegram init data. A direct request to the plaintext app
route returned HTTP 426 with `encrypted_transport_required`.
