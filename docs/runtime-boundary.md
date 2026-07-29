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
agent tool, one-time Computer key, a packaged public scope manifest, implemented
presets, requestable Custom-scope handling, detached poll/decrypt worker, owner-only
multi-account credential registry, account selection, and user-facing skill.
The platform owns stable connection ids, the central Web OAuth client, callback,
code exchange, identity and exact-grant validation, and short-lived encrypted
credential handoff.
Bare connect requests only `openid`, `email`, and `profile`. The manifest then
defines seven composable access presets: Mail Reader (`mail_reader`), Mail
Sender (`mail_sender`), Workspace Reader (`workspace_reader`), Mail Writer
(`mail_writer`), Inbox Manager (`inbox_manager`), Calendar
Coordinator (`calendar_coordinator`), and File Collaborator
(`file_collaborator`). Custom access can add exact manifest-listed scopes.
Mail Sender's `gmail.send` cannot read the inbox or manage drafts. Workspace
Reader's `gmail.readonly` also exposes Gmail settings. `gmail.compose` covers
drafts and sending because Google has no draft-only scope; `gmail.modify` covers reading,
composing, sending, drafts, labels, archive, and read state without immediate
permanent deletion; and the implemented `drive.file` workflow covers files
Tinyhat creates or files the user explicitly shares with the app, not other
Drive files.

The plugin normalizes redundant scopes and sends exact manifest metadata for
platform validation. The plugin's preliminary client-policy selection defaults
to `tinyhat-development` intentionally: the Computer cannot know which central
OAuth client the attested platform will select, and a production default would
reject valid development requests before the platform could decide. This
fallback does not authorize OAuth. The platform preflight is authoritative for
the exact final scopes and stamps the actual manifest and client policy before
the plugin may create local state, a worker, an authorization URL, or a Google
button. A missing preflight endpoint or malformed review rejection therefore
stops with a non-transient platform-not-ready result instead of inviting a retry.
Unknown, unimplemented, or legacy-only scopes produce `review_required` before
OAuth state, a detached worker, or a Google button exists. Implemented scopes
remain requestable while Google verification is pending; that verification
state stays visible in the manifest and Google may show its provider warning.
Historical profiles remain readable compatibility inputs. Separate
compatibility scope disclosures only label risks in historical grants or blocked
requests; they cannot become presets, requestable Custom scopes, or implemented
capabilities. `connect` with one account id unions current and requested access;
`set_permissions` replaces one selected account's local credential with the
exact presets and requestable Custom set, plus identity. A narrower replacement
stops the Computer from using removed scopes, but is not Google provider-side
granular revocation and does not erase consent history. Google consent is the
permission decision, so there is no separate plugin elevation ceremony.
Consumer skills and scripts can evolve across the same plugin/platform
boundary while the runtime continues to supply only the existing Computer
identity and plugin lifecycle.

Deployment preserves that boundary: merge and tag the plugin first without
promoting a channel, deploy the compatible platform enforcement, and only then
advance `channels/latest` or `channels/lts` to the new plugin commit.
The auth plugin does not implement Google service operations. A
generic `tinyhat_google_workspace_app` bridge lends one selected account's
current access token to an isolated, manifest-verified root-owned `gws` child.
It accepts only the API namespaces audited for the pinned `gws` release while
retaining local, synthetic, auth/setup/login/export/mcp blocks and process/output
limits. A granted scope may precede CLI operation support. Its operation-level write
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
