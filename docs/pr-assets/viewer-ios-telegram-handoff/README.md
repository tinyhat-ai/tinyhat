# iOS Telegram viewer handoff evidence

These screenshots contain no customer data, production grants, or private
Telegram conversations. The mobile capability screenshots use synthetic
session identifiers; the Telegram Web screenshot shows only the rendered local
test page, with its development URL and session identifier outside the crop.

- `ios-miniapp-loading-only.png`: native Mini App state before the Telegram
  main-button action; the page remains spinner-only.
- `ios-telegram-browser-handoff.png`: no-service-worker Telegram browser state;
  it offers one external-browser action and never shows an access-code form.
- `ios-browser-public-open.png`: the external browser consumed a one-time
  link-only handoff and opened the encrypted synthetic app without a code.
- `encrypted-navigation.png`: the normal service-worker path opened the same
  encrypted app and preserved relative navigation.
- `telegram-web-link-only-e2e.png`: a fresh Hermes Computer created through the
  invitation and assignment flow shared a real development link-only session;
  opening that link from Telegram Web rendered the app without a code gate.
- `telegram-web-owner-miniapp-e2e.png`: the same assigned owner opened a fresh
  code-protected session through its Telegram Mini App button; Telegram owner
  authentication rendered the app directly without exposing the code form.

The no-service-worker states were exercised in mobile Chromium with the service
worker API disabled to reproduce iOS Telegram's `WKWebView` capability boundary.
The Mini App path also used a synthetic Telegram Web App bridge to verify the
native main-button callback and external-browser URL. This is browser-driven
regression evidence, not a screenshot from a production user session.
