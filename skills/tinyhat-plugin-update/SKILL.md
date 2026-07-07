---
name: tinyhat-plugin-update
description: Check or apply Tinyhat plugin channel updates. Use when the live Tinyhat plugin is behind channels/lts or channels/latest, update_available is true, target_ref_changed is reported, or current tools/skills look stale.
---

# Tinyhat Plugin Update

Use this when the current Hermes agent may be running an older Tinyhat
plugin than the configured channel.

Start with a read-only check:

```json
{"action": "status"}
```

This compares the installed Tinyhat plugin with the configured target
channel, usually `channels/lts`. If `update_available` is true or the
decision is `target_ref_changed`, the Computer is still running an older
plugin checkout.

Only apply the update when the user or operator asks you to update this
Computer's plugin. Then call:

```json
{"action": "update", "confirmed": true, "restart_gateway": true}
```

The update path uses the installed Tinyhat runtime command
`update_tinyhat_plugin`. With `restart_gateway=true`, it then uses the
installed `stop_hermes` and `start_hermes` commands so the long-running
Telegram gateway reloads plugin tools and commands.

Do not use arbitrary shell commands to clone, edit, or install plugin
files manually. Use the Tinyhat runtime update path so the installed
source metadata and channel commit remain auditable.
