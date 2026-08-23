---
name: tinyhat-local-app-sharing
description: Share, list, or stop a short-lived Tinyhat link to an HTTP app running on this Computer's localhost when the user asks to see a local app, preview, dashboard, or development server. Do not use for files, terminal access, arbitrary URLs or hosts, non-HTTP services, or pages containing secrets.
---

# Tinyhat Local App Sharing

Use `tinyhat_local_app_sharing` to let the user review a non-sensitive HTTP
application already running on this Computer. By default Tinyhat returns a
public link and a four-digit numeric code. The tool also sends the owner a
native **View app** Telegram Mini App button. The signed owner opens that
button without entering a code; the same link can be opened in any other
browser by entering the code. When the user explicitly wants anyone with the
link to have access, create a link-only session instead.
Ordinary, non-sensitive shares use normal HTTPS transport by default and can
render directly inside Telegram, including Telegram on iOS. When the user asks
for browser-to-Computer encryption, set `encryption_mode` to `encrypted`. The
encrypted link includes a Computer-key fingerprint in its URL fragment;
preserve it exactly. Telegram iOS may need to hand an encrypted share off to
the device browser when its embedded WebView lacks the required service worker.

## Create a share

1. Determine the exact numeric localhost port. Never pass a hostname or URL.
2. Make sure the app is already listening on that port.
3. Call:

```json
{
  "action": "create",
  "port": 3000,
  "label": "Campaign preview",
  "ttl_seconds": 900
}
```

`encryption_mode` defaults to `plain`. Use `"encrypted"` only when the user
asks for the additional browser-to-Computer encryption layer or the page is
sensitive enough to require it:

```json
{
  "action": "create",
  "port": 3000,
  "label": "Encrypted campaign review",
  "ttl_seconds": 900,
  "encryption_mode": "encrypted"
}
```

`access_mode` controls visibility. It defaults to `code`, which is private:
normal browsers require the four-digit code, while the assigned owner's valid
Telegram credentials provide a shortcut around that gate. If Telegram
credentials are absent or invalid, the same code form is shown. Set
`"access_mode": "link"` only when the user asks for a public share that anyone
holding the complete link can open without a code, in Telegram or any other
browser:

```json
{
  "action": "create",
  "port": 3000,
  "label": "Open campaign review",
  "ttl_seconds": 900,
  "access_mode": "link"
}
```

4. Check `telegram_button_sent`. When it is `true`, tell the user the **View
   app** button is ready and do not send a duplicate button. When it is `false`,
   send the returned `link`, expiry, and (for `access_mode: code`) four-digit
   `access_code` yourself. A link-only session returns no access code.

If the user wants to review two apps or ports, create two sessions. Each gets
its own link, access mode, expiry, and revocation boundary.

## List or stop shares

List active sessions when the user asks what is shared:

```json
{"action": "list"}
```

Revoke the exact session immediately when the user asks to stop sharing or the
review is finished:

```json
{"action": "revoke", "session_id": "las_..."}
```

## Safety boundaries

- Share only an application the user asked to review or that is an expected
  review artifact for the current task.
- Do not share credential pages, secret viewers, admin consoles, personal
  messages, terminals, or apps containing unrelated user data.
- This first slice is read-only HTTP: browser `GET` and `HEAD` work; writes and
  WebSockets are not supported.
- Treat the link and any code as short-lived access material. A link-only URL
  is itself sufficient for access, so use that mode only at the user's request.
  Send access material only in the owner's Telegram chat; do not put it in
  logs, source files, commits, issue comments, or documentation.
- For encrypted shares, never remove, shorten, or reconstruct the URL fragment.
  It binds the browser to this share's Computer-local key; an encrypted link
  without it fails closed.
- The plugin accepts only a numeric loopback port. Never work around that limit
  with a proxy to another host or network address.
- Revoke the session after the review when continued access is unnecessary.
- If Tinyhat reports that sharing is unavailable, explain that the preview
  could not be exposed and continue working locally. Do not modify the runtime
  or create an alternative public tunnel.

## Platform boundary

The plugin owns this skill and the Computer-local gateway. Versioned Tinyhat
platform APIs own one named tunnel and opaque hostname per Computer, plus
session identity, access mode, code verification where required, browser
grants, expiry, and revocation.
The plugin keeps this Computer's connector token private and runs the pinned
Cloudflare connector. Cloudflare infrastructure carries HTTPS traffic to the
loopback-only gateway. Plain shares use that ordinary HTTPS transport;
encrypted shares add browser-to-Computer end-to-end encryption. The Tinyhat
platform API receives authorization and expiry metadata, not page contents,
requests, responses, or upstream app cookies. The Tinyhat runtime is not part
of this capability.
