# iOS Telegram viewer handoff evidence

These screenshots use a synthetic localhost application and synthetic session
identifiers. They contain no customer data, production grants, or private
Telegram conversations.

- `ios-miniapp-loading-only.png`: native Mini App state before the Telegram
  main-button action; the page remains spinner-only.
- `ios-telegram-browser-handoff.png`: no-service-worker Telegram browser state;
  it offers one external-browser action and never shows an access-code form.
- `ios-browser-public-open.png`: the external browser consumed a one-time
  link-only handoff and opened the encrypted synthetic app without a code.
- `encrypted-navigation.png`: the normal service-worker path opened the same
  encrypted app and preserved relative navigation.

The no-service-worker states were exercised in mobile Chromium with the service
worker API disabled to reproduce iOS Telegram's `WKWebView` capability boundary.
The Mini App path also used a synthetic Telegram Web App bridge to verify the
native main-button callback and external-browser URL. This is browser-driven
regression evidence, not a screenshot from a production user session.
