---
name: hat-authoring
description: Create and evolve a free public or private Tinyhat Hat through chat, including its audience, safe repo files, and Computer-local credentials.
---

# Hat authoring

Use this skill when the user asks to create, inspect, or modify a Hat.

## Create

1. Get the Hat's human-readable name and ask whether it should be `public` or
   `private`. Public Hats can be installed by every Tinyhat user. Private Hats
   can be installed only by the creator and named Tinyhat users. A short key,
   default Telegram bot username, and default Telegram bot display name are
   optional. For a private Hat, collect any initial user names, Telegram
   handles, or verified emails the creator wants to allow.
2. Call `tinyhat_hats` with `action="create"`, `name`, `access_mode`, and any
   supplied `allowed_users`, `key`, bot defaults, and compatibility
   requirements. Hats are always free; never ask for pricing or subscription
   details.
3. Call `tinyhat_hats` with `action="repository_checkout"` and the returned
   canonical handle. This creates the normal local Git checkout without putting
   a GitHub credential in its remote URL or config.
4. Report the returned canonical handle and share URL. Say that the private
   repository was created only when `repository_created` is true. Explain that
   a public Hat is available to every Tinyhat user, while a private Hat is
   available only to its named users.

Do not ask for account or owner ids; Tinyhat derives them from this Computer.

## List or inspect

- Call `tinyhat_hats` with `action="list"` to list up to 100 hats.
- Call it with `action="get"` and the returned key or canonical handle to
  inspect one hat.

## Update Hat metadata

Call `tinyhat_hats` with `action="update"`, the current Hat `identifier`, and
one or more of:

- `public_title` for the marketplace title;
- `access_mode` to switch between `public` and `private`;
- `add_user` or `remove_user` with one exact Tinyhat name, Telegram handle, or
  verified email to change a private audience;
- `default_bot_username` for the Telegram bot username proposed during agent
  creation;
- `default_bot_display_name` for the proposed Telegram bot display name; or
- `new_key` for the final segment of the namespaced canonical handle.
- `minimum_computer_type_key`, `minimum_plugin_version`, and
  `minimum_runtime_version` for compatibility requirements.

Changing a Hat to public does not expose its private repository or credential
values. Removing a user blocks new installations for that user; it does not
silently uninstall a Hat already running on their Computer.

The account namespace is derived from the Computer and cannot be changed by
the model. A handle change renames the existing private repository, preserves
the Hat and its files, keeps former public links resolving to the Hat, and
moves the encrypted Computer-local credential store to the new handle. Report
the new canonical handle and share URL when they change.

## Delete a Hat

Use the compatibility `delete` action to retire a Hat only after the user
explicitly asks to retire that exact Hat. Explain the consequences before
confirming: the Hat disappears from the owner's Hat list, its public page, and
new installations; its private repository is deleted from the Hat's GitHub
organization only after the provider acknowledges deletion; creator
Computer-local package state is removed; Tinyhat retains platform and
installation history; and already-installed consumer agents and their local
state are not deleted.

Call `tinyhat_hats` with `action="delete"`, the canonical `identifier`, and
`confirmed=true`. Retirement removes the creator Computer-local secret bundle
and encryption key without returning a secret value. Report the returned
repository and local-store outcomes honestly. Also report
`local_checkout_cleanup_complete` honestly: successful retirement removes
verified creator checkouts for both the current handle and former handles while
leaving unrelated Hat checkouts untouched. Never claim the Hat database record,
installation history, or already-installed consumer agents were deleted.

## Add or update repo content

1. Call `tinyhat_hats` with `action="repository_checkout"` and the Hat
   identifier. Use the returned local path as the working directory. Inspect
   the current files and Git status before editing.
2. Create, update, rename, or remove the requested files with the Computer's
   normal file tools. Several related files may change together.
3. Call `tinyhat_hats` with `action="repository_status"` and review every
   changed path. Do not include unrelated work.
4. Call `tinyhat_hats` with `action="repository_sync"`, the exact changed
   `paths`, and one concise, atomic `message`. Tinyhat commits, pushes, and
   verifies the new GitHub head without returning the short-lived credential.
5. Report the synced paths and verified head SHA. Do not claim success unless
   `pushed=true`.

`put_file` remains the compatibility path for Hats whose error says they use
the original repository integration. New `tinyhat-ai` Hats use the local Git
workflow above so repository contents travel directly between the Computer and
GitHub rather than through Tinyhat's file API.

Before creating, reviewing, or updating any skill, load
`tinyhat:tinyhat-skill-authoring` and follow its naming, trigger-boundary,
length, progressive-disclosure, and validation guidance. Use
`skills/<skill-name>/SKILL.md`; a later call to the same path updates it in a
new commit, so repo history remains the undo trail.

Never put an API key, token, password, private key, `.env` file, secret file,
or credential file in the repo. The platform rejects secret-shaped paths and
private-key material, but the skill must avoid sending secret values at all.

Never put a lease token in a Git URL, `git config`, `gh auth`, a file, a shell
command, or chat. The Computer's credential helper obtains an exact-repository
lease for Git. If the user explicitly asks to stop renewal, call
`repository_reset` with `confirmed=true`; report any residual expiry honestly
and explain that the local clone remains until the Computer is wiped.

## Keep the public capability overview current

The Hat's public page leads with what an agent can do, then lists its skills
and tools. Keep that overview accurate whenever the repo changes:

1. Write a root `HAT.md` with frontmatter `name` equal to the Hat key and a
   short `description` that completes the sentence "An agent with this Hat can
   ...". Write only the grammatical completion after `can`; do not repeat the
   `An agent with this Hat can` prefix. Describe the work itself; do not explain
   what a Hat is.
2. Keep each skill in `skills/<name>/SKILL.md` with a clear frontmatter `name`
   and `description`. The public page lists these descriptions without exposing
   the private file body.
3. Define required credentials with precise purposes. The public page publishes
   each purpose in the Tools list and derives a readable label from each env
   name; it never shows the value. Use provider- or capability-shaped names,
   and keep consumer identity and private data out of credential names and
   purposes.
4. After adding, removing, or materially changing skills, update `HAT.md` so
   its one-sentence description still summarizes the combined capability.

Do not put consumer identity, private data, repository URLs, credential names,
or secret values in the public description. Keep consumer identity and private
data out of credential names and purposes too, because derived labels and the
purpose text appear in the public Tools list.

## Define and configure Hat credentials

1. Get the Hat identifier plus every meaningful env-style name and short
   purpose. Never ask for any value in chat.
2. For each new or changed field, call `tinyhat_hats` with
   `action="define_credential"`, `identifier`, `credential_name`, and
   `description`. This writes value-blind metadata only and advances the Hat
   repository head. Finish every credential-definition call before starting a
   repository checkout/edit/sync sequence. Never run credential-definition and
   repository-mutation actions in parallel. If a credential definition changes
   after checkout, call `repository_checkout` again before inspecting status or
   syncing files so the local base matches the new remote head.
3. After every field is defined, call `tinyhat_hats` once with
   `action="configure_credentials"` and the Hat `identifier`.
4. Tinyhat sends one expiring **Enter credentials** button. The user sees every
   field on one page. Fields with a Computer-local value are marked as saved
   without revealing that value; leaving one blank preserves it, while an
   entered value replaces only that field. New fields are required. The browser
   encrypts the submitted values with the Hat's Computer-local key. The Computer
   merges them into the Hat's
   local package store under `~/.tinyhat/hats/<owner>/<hat>/secrets.json` for
   authorized consumers; plaintext is not stored there. It does not load the
   values into this agent's Hermes environment and does not restart Hermes.

Calling `configure_credentials` again replaces only the values entered in that
submission and preserves saved blank fields. The Hat preview always asks the
assigned Computer to open a fresh encrypted form so its saved-value indicators
are current. Do not claim the save succeeded until Telegram confirms **Hat
credentials saved**.

## List or remove Hat credentials

- Call `tinyhat_hats` with `action="list_credentials"` and the Hat identifier.
  Return names and descriptions only; never infer or claim a value. When
  `local_value_status` is `available`, use each field's `has_local_value` as the
  authoritative saved-state. When it is `unavailable`, say that saved-state
  could not be checked; do not turn that into `No`.
- Remove only after the user explicitly asks to remove an exact credential from
  an exact Hat. Then call `tinyhat_hats` with `action="remove_credential"`,
  `credential_name`, and `confirmed=true`. This deletes the local value and its
  value-blind repo metadata. Report `local_value_removed` honestly.
- To recreate a removed credential, define it again, then call
  `configure_credentials` once after all requested names are ready.
