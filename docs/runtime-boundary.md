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
agent tool, one-time Computer key, fixed named capability request, detached
poll/decrypt worker, permission-protected credential custody, and user-facing
skill. The platform owns the central Web OAuth client, callback, code exchange,
identity and allowlist validation, and short-lived encrypted credential handoff.
The default profile fixes `google_workspace_readonly_v1` to services `identity`,
`gmail`, `calendar`, and `drive`, with basic identity plus the official Gmail,
Calendar, and Drive read-only scopes. Neither the user nor agent can supply
arbitrary scopes. A separately confirmed `google_workspace_gmail_send_v1`
upgrade adds only `gmail.send`; it does not add `gmail.compose`, and permission
upgrade is not confirmation for an actual send. Consumer skills and scripts
can evolve across the same plugin/platform boundary while the runtime continues
to supply only the existing Computer identity and plugin lifecycle.
The auth plugin does not implement Gmail, Calendar, or Drive operations. A
generic `tinyhat_google_workspace_app` bridge lends one current access token to
an isolated, manifest-verified root-owned `gws` child; verified official gws skills own all
service-specific argv and interpretation. The platform uses the central OAuth
client secret for encrypted token refresh. No runtime change is involved.

The plugin-owned app manager installs pinned official Linux x86_64 or aarch64
`gws` artifacts and operation skills after user approval. It verifies hardcoded
hashes, installs transactionally, and removes only unchanged managed files. A
Tinyhat shared shim makes every operation skill use the existing token bridge,
never Google Cloud setup or `gws auth`. This also requires no runtime change.

Google disconnect follows the same boundary. The plugin starts a
generation-bound Computer worker and calls platform APIs. The platform sends a
native Telegram `web_app` message with exactly one **Revoke this Computer’s
access** button, authenticates the first tap, and edits that same message to
show final **Confirm revoke** and **Cancel** buttons. Confirm or cancel removes
the buttons. Cancel preserves the local
credential. Confirm lets only the matching worker delete the matching local
credential, after which the platform marks that Computer disconnected. No URL,
token, or intent identifier is exposed to the model, and no runtime callback or
command is added.

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
