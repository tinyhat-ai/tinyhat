---
name: commit
description: Use when making a commit to the tinyhat repo. If a maintainer-private bot identity table is present in CLAUDE.local.md, use the inline-override pattern described here so agent commits are SSH-signed under a bot identity. Otherwise commit as whoever owns the local git config. Also covers Conventional Commits. Invoke before every commit.
---

# commit — how to land a commit on tinyhat

## 1. Decide which identity to use

Before you run `git commit`, check whether a **bot identity table** is
defined in the repo's `CLAUDE.local.md` (gitignored, maintainer-only).

- **Table present → use the inline-override pattern below.** You are
  operating on a machine that has bot SSH keys provisioned, and every
  agent commit must be signed under its own bot identity (not the
  maintainer's).
- **Table absent → just `git commit` normally.** Commit as whoever
  owns the local git config (typically an external contributor or a
  fresh clone with no bots set up). No inline overrides needed.

The rest of this skill describes the inline-override pattern for the
first case. If you're in the second case, skip to section 5
(Conventional Commits) and section 6 (non-negotiables that apply to
everyone).

## 2. Preflight (once per machine, not per repo)

Pick your row from the bot identity table in `CLAUDE.local.md` and
verify the credentials are live:

```bash
# Substitute your row's key filename and SSH host alias.
test -f "$HOME/.ssh/<agent-key>.pub" && echo "key OK"
ssh -T git@<ssh-host-alias> 2>&1 | head -1   # must greet your bot GitHub user
echo test | ssh-keygen -Y sign \
  -f "$HOME/.ssh/<agent-key>" -n git > /dev/null && echo "sign OK"
```

If anything fails — missing key, wrong greeting, sign error — **stop**.
Use the [`add-agent`](../add-agent/SKILL.md) skill to provision the
missing piece. Never fall back to the maintainer's identity to keep
going.

## 3. Commit with inline overrides

Fill in the four values from your `CLAUDE.local.md` row plus the
shared allowed-signers file path:

```bash
git \
  -c user.name="<bot author name>" \
  -c user.email="<bot author email>" \
  -c user.signingkey="$HOME/.ssh/<agent-key>.pub" \
  -c gpg.format=ssh \
  -c commit.gpgsign=true \
  -c gpg.ssh.allowedSignersFile="$HOME/.ssh/<allowed-signers-file>" \
  commit -m "<type>(<scope>): <subject>"
```

For a longer session, define a shell function once and reuse it:

```bash
bot_git() {
  git \
    -c user.name="<bot author name>" \
    -c user.email="<bot author email>" \
    -c user.signingkey="$HOME/.ssh/<agent-key>.pub" \
    -c gpg.format=ssh \
    -c commit.gpgsign=true \
    -c gpg.ssh.allowedSignersFile="$HOME/.ssh/<allowed-signers-file>" \
    "$@"
}
# then: bot_git commit -m "..." ; bot_git tag ... ; etc.
```

## 4. After the commit (inline-override path)

Verify with the same allowed-signers pointer you used at commit time:

```bash
git -c gpg.ssh.allowedSignersFile="$HOME/.ssh/<allowed-signers-file>" \
  log --show-signature -1      # "Good git signature for <bot-email>"
git log --pretty=fuller -1     # Author + Committer = the bot
```

Seeing `error: gpg.ssh.allowedSignersFile needs to be configured and
exist` from a plain `git log --show-signature` is expected and just
means the verify step has no pointer — the signature is still there in
the commit object (`git cat-file -p HEAD | head` shows the `gpgsig`
block).

If either is wrong and the commit has not been pushed, re-run with the
correct inline overrides, amending with
`git commit --amend --reset-author ... -C HEAD`. If the commit was
pushed and shared, leave it and open a new commit noting the mistake —
never rewrite shared history.

## 5. Conventional Commits (everyone)

Format: `<type>(<optional scope>): <subject>`, imperative, **under 72
characters**. Body optional, explains *why*, wrap at ~72.

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`,
`build`. Breaking change: append `!` to the type or add a
`BREAKING CHANGE:` footer.

Separate commits for separate concerns. Don't bundle a refactor with a
feature.

## 6. Non-negotiables

- Never push directly to `main`. Commits travel through PRs — see
  [`open-pr`](../open-pr/SKILL.md).
- Never use `--no-verify`, `[skip ci]`, or amend a pushed-and-shared
  commit unless the maintainer explicitly asked.
- Never commit keys, tokens, or any credential. Never commit content
  from a gitignored `CLAUDE.local.md` or any other maintainer-private
  source.

**Additional rules on the inline-override path (when a bot identity
table is present):**

- Never commit without the inline `-c` overrides. A silent `git commit`
  picks up whoever owns the local git config, which isn't the bot.
- Never set agent identity as `git config --local`. Local config
  belongs to whoever cloned the repo.
- Never reuse one agent's signing key on another agent.
