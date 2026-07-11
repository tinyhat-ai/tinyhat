---
name: tinyhat-google-workspace-app-manager
description: Inspect or, after explicit approval, install or uninstall Tinyhat's pinned Google Workspace CLI app and verified official Gmail, Calendar, and Drive operation skills. Use when the Google Workspace bridge says the managed gws app or matching skill is unavailable.
---

# Tinyhat Google Workspace app manager

Use `tinyhat_google_workspace_app_manager` for the separately managed operation
app, not for Google authentication:

- Check safe installation metadata with `{"action": "status"}`.
- If the app or a compatible operation skill is unavailable, explain that
  Tinyhat can install its pinned, integrity-verified Google Workspace CLI
  integration. Ask the user for approval. Do not install automatically.
- Only after approval, install with
  `{"action": "install", "confirmed": true}`.
- Uninstall only after explicit approval with
  `{"action": "uninstall", "confirmed": true}`.

The first managed release supports Linux x86_64 and aarch64 Computers. It installs the
pinned official `googleworkspace/cli` binary and verified official Gmail,
Calendar, and Drive operation skills. Tinyhat also installs a shared integration
shim that overrides upstream authentication setup: never run `gws auth`, never
start a second OAuth flow, and never ask for a Google Cloud project, OAuth
client, client secret, credentials JSON, `gcloud`, or a raw token.

After installation, return to `tinyhat:tinyhat-google-workspace`. The official
operation skill constructs bounded argv, and `tinyhat_google_workspace_app`
injects the existing assignment-verified Tinyhat token into one isolated child.

Uninstall removes exact unchanged files recorded in Tinyhat's root-only managed
manifest. Modified managed files are preserved in root-only quarantine outside
active skill paths; unmanaged files are left untouched. Results use only safe
component names.
