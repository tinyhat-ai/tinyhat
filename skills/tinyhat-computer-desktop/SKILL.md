---
name: tinyhat-computer-desktop
description: Open a short-lived, view-only connection to this Computer's desktop when the owner asks to see its screen, desktop, browser, or current visual state. Do not use for terminal access or for sharing a single report or web page.
---

# Computer desktop

Use this capability when the owner asks to see this Computer's live desktop or
screen. For a single report, chart, dashboard, or web page, use a Visual instead.

## Open the desktop

1. Call `tinyhat_computer_desktop` with no arguments.
2. Tell the user the desktop connection is ready and view-only.
3. Send the returned `link` and the six-digit `access_code`.
4. The tool sends an **Open desktop** Mini App button when Telegram delivery is
   available. Do not send a second button or claim it was sent when
   `telegram_button_sent` is false.
5. Mention the expiry in natural language. Do not mention VNC, Guacamole,
   Tailscale, ports, tunnels, or gateway implementation details.

Inside the assigned Telegram Mini App, the owner is verified automatically and
does not enter the code. The same link works in any other browser after entering
the code.

Never claim the user can control the desktop. This first version is view-only.
