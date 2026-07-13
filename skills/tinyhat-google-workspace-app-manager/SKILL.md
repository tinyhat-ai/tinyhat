---
name: tinyhat-google-workspace-app-manager
description: Inspect or, after explicit approval, install or uninstall Tinyhat's pinned Google Workspace CLI app. Hermes's bundled Google Workspace skill owns operation guidance. Use when the Google Workspace bridge says the managed gws app is unavailable.
---

# Tinyhat Google Workspace app manager

Use `tinyhat_google_workspace_app_manager` for the separately managed operation
app, not for Google authentication:

- Check safe installation metadata with `{"action": "status"}`.
- Treat that status as authoritative. If it reports `status: "installed"` and
  `binary_ready: true`, proceed directly to the Google Workspace skill and
  bridge. Do not reinstall.
- If status reports that the app is absent or its binary has an integrity
  mismatch, explain that
  Tinyhat can install its pinned, integrity-verified Google Workspace CLI
  integration. Ask the user for approval. Do not install automatically.
- Only after approval, install with
  `{"action": "install", "confirmed": true}`.
- Uninstall only after explicit approval with
  `{"action": "uninstall", "confirmed": true}`.

The managed release supports Linux x86_64 and aarch64 Computers and installs
only the pinned official `googleworkspace/cli` binary. Hermes already bundles
the `google-workspace` skill for Gmail, Calendar, Drive, Sheets, and Docs
operation guidance. Tinyhat's current bridge and OAuth profiles execute Gmail,
Calendar, and Drive namespaces; do not promise Sheets or Docs access yet.
`/opt/tinyhat/bin/gws` is intentionally private to the bridge: never look for
it with `which`, require it on `PATH`, or execute it directly.
Tinyhat overrides only the native skill's authentication/execution path:
never run `gws auth` or its setup scripts, never start a second OAuth flow, and
never ask for a Google Cloud project, OAuth client, client secret, credentials
JSON, `gcloud`, or a raw token.

If the bridge returns `app_unavailable` while manager status is still
`installed` with `binary_ready: true`, do not loop reinstall. Load
`tinyhat:tinyhat-plugin-update`, report the installed and target plugin
versions/ref from its status, and apply an available plugin update only after
approval with `restart_gateway: true`. If the plugin is already current or the
update fails, report a plugin/host compatibility failure with the manager and
plugin status; do not suggest new Google credentials or OAuth setup.

After installation, return to `tinyhat:tinyhat-google-workspace`. Load Hermes's
built-in `google-workspace` skill for operation semantics, then use
`tinyhat_google_workspace_app`; it injects the existing assignment-verified
Tinyhat token into one isolated child.

Uninstall removes exact unchanged files recorded in Tinyhat's root-only managed
manifest. An approved reinstall from the previous manager layout also retires
its obsolete top-level gws skills, preserving modified copies in root-only quarantine.
Hermes's bundled skill and all unmanaged files remain untouched.
