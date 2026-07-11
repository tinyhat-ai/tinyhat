---
name: tinyhat-google-workspace-app-manager
description: Inspect or, after explicit approval, install or uninstall Tinyhat's pinned Google Workspace CLI app. Hermes's bundled Google Workspace skill owns operation guidance. Use when the Google Workspace bridge says the managed gws app is unavailable.
---

# Tinyhat Google Workspace app manager

Use `tinyhat_google_workspace_app_manager` for the separately managed operation
app, not for Google authentication:

- Check safe installation metadata with `{"action": "status"}`.
- If the app is unavailable, explain that
  Tinyhat can install its pinned, integrity-verified Google Workspace CLI
  integration. Ask the user for approval. Do not install automatically.
- Only after approval, install with
  `{"action": "install", "confirmed": true}`.
- Uninstall only after explicit approval with
  `{"action": "uninstall", "confirmed": true}`.

The managed release supports Linux x86_64 and aarch64 Computers and installs
only the pinned official `googleworkspace/cli` binary. Hermes already bundles
the `google-workspace` skill for Gmail, Calendar, Drive, Sheets, and Docs
operation guidance. Tinyhat overrides only its authentication/execution path:
never run `gws auth` or its setup scripts, never start a second OAuth flow, and
never ask for a Google Cloud project, OAuth client, client secret, credentials
JSON, `gcloud`, or a raw token.

After installation, return to `tinyhat:tinyhat-google-workspace`. Load Hermes's
built-in `google-workspace` skill for operation semantics, then use
`tinyhat_google_workspace_app`; it injects the existing assignment-verified
Tinyhat token into one isolated child.

Uninstall removes exact unchanged files recorded in Tinyhat's root-only managed
manifest. An approved reinstall from the previous manager layout also retires
its obsolete top-level gws skills, preserving modified copies in root-only quarantine.
Hermes's bundled skill and all unmanaged files remain untouched.
