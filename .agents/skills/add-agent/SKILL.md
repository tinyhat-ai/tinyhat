---
name: add-agent
description: Use when the maintainer onboards a new AI coding agent (Aider, Gemini CLI, Windsurf, Cline, a new Claude/Cursor/Codex instance on a new machine, etc.) to contribute to the tinyhat repo under a bot identity. Covers machine-user provisioning, SSH key + host alias setup, adding the agent row to the private bot identity table in CLAUDE.local.md, and the `.gitignore` pattern for the agent's machine-local state.
---

# add-agent — onboard a new agent to tinyhat

This is a maintainer-level procedure run on the maintainer's own
machine. An agent may propose the changes as a PR, but the GitHub
machine-user and SSH key provisioning in steps 1–2 must be done by a
human with access to the tinyhat-ai GitHub org.

Per the identity model defined in [`commit`](../commit/SKILL.md),
agents do **not** claim the repo's local git config. Onboarding is
about setting up the machine-level ingredients an agent needs so it
can inject its identity inline on every git write, and recording those
ingredients in the maintainer's gitignored `CLAUDE.local.md` so the
other skills can look them up.

## 1. Provision a distinct GitHub identity

The new agent needs its own:

- **GitHub machine-user account**, added to the `tinyhat-ai` org as a
  member (not just a collaborator — membership is required so the
  fine-grained PATs below can have `tinyhat-ai` as Resource Owner).
- **SSH key** at `~/.ssh/<agent>_ed25519` (+ `.pub`), no passphrase so
  unattended signing works. Register the public key on the machine
  user as **both** an Authentication key and a Signing key. Never
  share keys between agents.
- **Fine-grained PAT** with Resource Owner `tinyhat-ai`, scoped to
  the active `tinyhat-ai/*` repos the agent will work in (currently
  just `tinyhat`), permissions `Contents: read/write`, `Pull requests:
  read/write`, `Issues: read/write`, `Metadata: read`. Approve at the
  org level if the org requires approval.

## 2. Set up SSH host alias and allowed-signers

Add to `~/.ssh/config`:

```sshconfig
Host github.com-<agent>
  HostName github.com
  User git
  IdentityFile ~/.ssh/<agent>_ed25519
  IdentitiesOnly yes
```

Append the agent's public key to the shared verifier file (e.g.
`~/.ssh/<project>_agents_allowed_signers` — maintainer picks the name),
scoped by the agent's committer email:

```
<agent-bot-email> ssh-ed25519 <...> <comment>
```

This keeps `git log --show-signature` working for every bot's commits
with no per-repo config changes.

## 3. Register the agent

Two places, one committed, one private:

1. **Private (maintainer's machine only).** Add a row for the new agent
   to the **Bot identity table** in `CLAUDE.local.md` (gitignored).
   Include: Author name, Author email, Signing key path, SSH host
   alias, GitHub user. The `commit` and `open-pr` skills look this
   table up at run time.
2. **Committed (in the onboarding PR).** Add the agent to the
   **Scope** list in [`AGENTS.md`](../../../AGENTS.md).

If the agent writes machine-local state (sessions, caches, chat
history, hook state) into the repo, add ignore rules to
[`.gitignore`](../../../.gitignore) **before** the agent's first
commit. Pattern:

```gitignore
# <Agent Name> — keep <shared-rules-path> if the agent uses it
.<agent>/sessions/
.<agent>/cache/
.<agent>/state/
```

If the agent reads a dedicated instruction file (like `CLAUDE.md`,
`.clinerules`, `.windsurfrules`), add a **thin** file that defers to
`AGENTS.md`. Do not duplicate policy.

Add the agent's bot PAT to `gh` so the onboarding PR can be opened
under the new agent's identity:

```bash
gh auth login --git-protocol https --hostname github.com --with-token \
  < /path/to/new-agent.pat
gh auth switch --user <maintainer-github-user>   # restore your default
```

## 4. First PR from the new agent

The onboarding PR is itself authored by the new agent — commits signed
with the new key via inline `-c` overrides (see
[`commit`](../commit/SKILL.md)), push via the new SSH host alias (see
[`open-pr`](../open-pr/SKILL.md)), PR opened through `gh auth switch`
to the agent's GitHub user. That end-to-end trip is the smoke test.

## 5. Non-negotiables

- Never reuse one agent's SSH key on another agent.
- Never add an agent to the scope list before the machine user + key
  + allowed-signers entry are all provisioned and the inline-override
  preflight passes.
- Never omit the `.gitignore` rules — a misconfigured agent's first
  commit can leak machine-local state that's hard to scrub later.
- Never set the new agent's identity as the repo's `--local` git
  config. Agents assert identity per-command, not per-repo.
