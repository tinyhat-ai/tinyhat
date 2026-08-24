---
name: tinyhat-local-app-sharing
description: Create, list, or expire short-lived Tinyhat Visuals when visual communication would help the user, including reports, charts, dashboards, previews, and interactive explanations. Do not use for files, terminal access, arbitrary URLs or hosts, non-HTTP services, or pages containing secrets.
---

# Tinyhat Visuals

A **Visual** is a visual page you create and share with the user. Use Visuals as a
communication and reporting tool when a chart, dashboard, visual summary,
interactive explanation, or preview would make your answer easier to
understand than text alone.

## Goal

Turn work that benefits from visual storytelling into a clear, polished page
the user can explore, while presenting it as a Visual rather than exposing the
technical machinery used to create or share it.

Call `tinyhat_local_app_sharing` after the page is running on this Computer.
Keep implementation details such as localhost, servers, and port numbers out of
the user-facing message. Present the result as a Visual and explain what the user
will learn or be able to review there.

Good uses include:

- a chart that makes a trend or comparison clear;
- a visual report or status dashboard;
- an interactive table, timeline, map, or model;
- a design, document, or feature preview;
- a small purpose-built page that communicates a result more clearly.

Do not create a Visual just to repeat a short answer that is already clear in
text.

## Create a Visual

1. Decide what the Visual should communicate and give it a descriptive,
   user-facing label such as `Weekly revenue report` or `Campaign forecast`.
2. Build and start the page locally. Internally determine its numeric loopback
   port; never pass a hostname or URL to the tool.
3. Create the Visual:

```json
{
  "action": "create",
  "port": 3000,
  "label": "Weekly revenue report",
  "button_label": "Open report",
  "ttl_seconds": 900
}
```

4. Tell the user what the Visual contains and that it is ready. Do not mention
   its port, server, localhost, or the underlying application unless the user
   explicitly asks for technical details.

The tool sends the owner a native Telegram Mini App button. Its default label
is **Open visual**. If the user asks for specific wording, pass it as
`button_label`. Otherwise, use a short content-specific action when it improves
clarity, such as **Open report**, **Open forecast**, or **Review dashboard**.
Never call the shared result an app in user-facing button text. When
`telegram_button_sent` is `true`, do not send a duplicate button. When it is
`false`, send the returned link, expiry, and, for a private Visual, the four-digit
access code yourself.

### Choose access deliberately

Visuals are private by default. With `"access_mode": "code"`, a normal browser
requires the four-digit code, while the assigned owner's valid Telegram
credentials can open the Visual directly. If Telegram credentials are absent or
invalid, the same code form is shown.

Use `"access_mode": "link"` only when the user explicitly asks for a public
Visual or a Visual anyone with the complete link can open:

```json
{
  "action": "create",
  "port": 3000,
  "label": "Public campaign report",
  "ttl_seconds": 900,
  "access_mode": "link"
}
```

A public Visual returns no access code and opens for anyone holding the complete
link, in Telegram or any other browser.

### Choose encryption deliberately

Ordinary, non-sensitive Visuals use normal HTTPS transport and render directly
inside Telegram, including Telegram on iOS. Set `"encryption_mode":
"encrypted"` only when the user asks for browser-to-Computer encryption or the
content requires that additional protection:

```json
{
  "action": "create",
  "port": 3000,
  "label": "Encrypted financial report",
  "ttl_seconds": 900,
  "encryption_mode": "encrypted"
}
```

The encrypted link contains a Computer-key fingerprint in its URL fragment;
preserve it exactly. Telegram iOS may need to open an encrypted Visual in the
device browser when its embedded WebView lacks the required security feature.

## List or expire Visuals

List active Visuals when the user asks what is currently shared:

```json
{"action": "list"}
```

Describe them by label, purpose, visibility, and expiry. Do not expose their
internal port numbers.

Expire the exact Visual immediately when the user asks to stop sharing it or the
review is finished:

```json
{"action": "revoke", "session_id": "las_..."}
```

If the user wants to compare multiple reports or previews, create a separate
Visual for each one. Each Visual has its own link, access policy, expiry, and
revocation boundary.

## Safety boundaries

- Share only information the user asked to review or an expected visual
  artifact for the current task.
- Do not share credential pages, secret viewers, admin consoles, personal
  messages, terminals, or pages containing unrelated user data.
- Visuals support read-only HTTP `GET` and `HEAD`; writes and WebSockets are not
  supported.
- Treat the link and any code as short-lived access material. A public Visual's
  URL is itself sufficient for access, so use that mode only at the user's
  request. Send access material only in the owner's Telegram chat; do not put
  it in logs, source files, commits, issue comments, or documentation.
- For encrypted Visuals, never remove, shorten, or reconstruct the URL fragment.
  It binds the browser to this Visual's Computer-local key; an encrypted link
  without it fails closed.
- Internally, the tool accepts only a numeric loopback port. Never work around
  that limit with a proxy to another host or network address.
- Expire the Visual after the review when continued access is unnecessary.
- If Tinyhat reports that Visuals are unavailable, explain that the Visual could
  not be shared and continue working locally. Do not modify the runtime or
  create an alternative public tunnel.

## Platform boundary

The plugin owns this skill and the Computer-local gateway. Versioned Tinyhat
platform APIs own one named tunnel and opaque hostname per Computer, plus Visual
identity, access mode, code verification where required, browser grants,
expiry, and revocation.

The plugin keeps this Computer's connector token private and runs the pinned
Cloudflare connector. Cloudflare infrastructure carries HTTPS traffic to the
loopback-only gateway. Plain Visuals use that ordinary HTTPS transport;
encrypted Visuals add browser-to-Computer end-to-end encryption. The Tinyhat
platform API receives authorization and expiry metadata, not page contents,
requests, responses, or upstream cookies. The Tinyhat runtime is not part of
this capability.
