# Runtime Boundary

The Tinyhat runtime should stay boring. It keeps a Computer reachable and
trusted by the platform. It should not grow every product feature.

The plugin is where agent-facing product behavior belongs.

## Runtime Responsibilities

- Heartbeat
- Attestation
- Runtime command delivery
- Framework installation
- Plugin installation and update
- Safe runtime update plumbing

## Plugin Responsibilities

- Skills that teach the agent what Tinyhat can do.
- Small tools that expose named, safe capabilities.
- Framework adapter metadata.
- Public documentation that lets users inspect what is installed.

If a future feature is mainly "teach the agent how to use Tinyhat", it
belongs in this repo. If it is "keep the Computer alive and trusted", it
belongs in the runtime.

Google identity connection is a concrete example: the plugin supplies the
agent tool, one-time Computer key, recommended and legacy profiles, bounded
canonical custom-scope handling, detached poll/decrypt worker, owner-only
multi-account credential registry, account selection, and user-facing skill.
The platform owns stable connection ids, the central Web OAuth client, callback,
code exchange, identity and exact-grant validation, and short-lived encrypted
credential handoff.
The default `google_workspace_recommended_v1` bundle fixes services `identity`,
`gmail`, `calendar`, and `drive`, with basic identity plus `gmail.modify`,
`calendar.events`, and `drive.readonly`. The Gmail scope covers reading,
composing, sending, and inbox/draft/label management while messages and threads
cannot bypass Trash for immediate permanent deletion. For other Workspace
capabilities, the agent may request bounded canonical Google-owned user-OAuth
scopes with a short reason. The plugin adds identity, canonicalizes the set,
derives its services, and sends exact metadata for platform validation. The
32-scope and 4 KiB ceilings are transport and abuse-resistance bounds, not a
scope-value allowlist. Two official legacy scopes
are exact exceptions: `https://www.google.com/calendar/feeds` grants full
Calendar read/write access including sharing and permanent deletion, while
`https://www.google.com/m8/feeds` grants full Contacts read/write access including
permanent deletion. They map to `calendar` and `people`. The separate
`https://mail.google.com/` scope grants full Gmail access including permanent
deletion; other `https://www.google.com/...` legacy scope URLs remain invalid.
Legacy fixed profiles remain readable. `connect` with one account id unions
current and requested scopes;
`set_permissions` replaces one selected account's local credential with the
exact profile or custom set. A narrower replacement stops the Computer from
using removed scopes, but is not Google provider-side granular revocation and
does not erase consent history. Google consent is the permission decision, so
there is no separate plugin elevation ceremony. Consumer skills and
scripts can evolve across the same plugin/platform boundary while the runtime
continues to supply only the existing Computer identity and plugin lifecycle.
The auth plugin does not implement Google service operations. A
generic `tinyhat_google_workspace_app` bridge lends one selected account's
current access token to an isolated, manifest-verified root-owned `gws` child.
It accepts bounded Google service namespaces while retaining root auth/setup/
login/export/mcp blocks and process/output limits. Its operation-level write
confirmation binds both account id and argv and remains required independently
of OAuth consent. Hermes's bundled
`google-workspace` skill owns operation guidance; its local-client OAuth setup
and scripts are bypassed. The platform uses the central OAuth client secret for
encrypted token refresh. No runtime change is involved.

The plugin-owned app manager installs only a pinned official Linux x86_64 or
aarch64 `gws` binary after user approval. It verifies hardcoded hashes and
installs transactionally. A confirmed migration retires obsolete skills from
the prior manager layout without touching Hermes's bundled skill. The existing
token bridge replaces Google Cloud setup and `gws auth`. This also requires no
runtime change.

Google disconnect follows the same boundary. The plugin starts a
generation-bound Computer worker and calls platform APIs. The platform sends a
native Telegram `web_app` message with exactly one **Revoke this Computer’s
access** button, authenticates the first tap, and edits that same message to
show final **Confirm revoke** and **Cancel** buttons. Confirm or cancel removes
the buttons. Cancel preserves the local
credential. Confirm lets only the matching worker delete the selected local
account, after which the platform marks that connection disconnected. Other
accounts on the Computer remain available. No URL, token, or intent identifier
is exposed to the model, and no runtime callback or command is added.

This is local-only revocation. The shared development Google OAuth project means
the plugin does not call Google's provider-level token revocation endpoint;
doing so could affect grants used by other Computers. Other Tinyhat Computers
remain connected, so public wording must not claim that the user's Google grant
was revoked.

The current Computer process boundary is not privilege separation. Hermes,
plugin tools, and terminal commands run as uid 0, which also owns the `0600`
Google credential. The bridge hardens the normal capability path but cannot
hide that credential from a malicious root process. Moving credential custody
and token lending behind a lower-privilege broker is future production
hardening; it is not claimed by this plugin release.
