---
name: open-pr
description: Use when opening a pull request on the tinyhat repo. If a maintainer-private bot identity table is present in CLAUDE.local.md, push with the bot's SSH key and open the PR under the bot's GitHub user. Otherwise just push and open normally. Also covers branch naming and the no-self-merge rule. Invoke after commits land on a branch.
---

# open-pr — how to open a PR on tinyhat

## 1. Branch naming

- Agents: `<agent>/<short-topic>` — e.g.
  `claude-code-bot/fix-readme-typo`, `codex-bot/trim-rules`.
- Humans: `<handle>/<short-topic>`.
- One concern per branch. Rebase onto `main`; do not merge `main` into
  your branch.

## 2. Which identity to push and open under?

Check whether a **bot identity table** exists in `CLAUDE.local.md`
(gitignored, maintainer-only).

- **Table present** → use the bot's SSH key on push and switch `gh` to
  the bot's GitHub user for PR creation. Follow sections 3–4.
- **Table absent** → push and open the PR as whoever owns the local
  git / `gh` config. Skip sections 3–4 and read only section 5
  (non-negotiables).

## 3. Push with the agent's SSH key (inline-override path)

The repo's `remote.origin.url` is the plain
`git@github.com:tinyhat-ai/tinyhat.git`, so whoever owns the local SSH
default key can push normally. Agents inject their bot key per-push
with `GIT_SSH_COMMAND` inline (use your row's key filename):

```bash
GIT_SSH_COMMAND="ssh -i $HOME/.ssh/<agent-key> -o IdentitiesOnly=yes" \
  git push -u origin <branch>
```

Alternative if `GIT_SSH_COMMAND` is awkward: push through the bot's
SSH host alias as a one-off URL, no local remote rewrite needed:

```bash
git push git@<ssh-host-alias>:tinyhat-ai/tinyhat.git \
  HEAD:refs/heads/<branch>
```

Either way, do **not** set `remote.origin.url` to an alias — that would
trap the working-tree owner into always pushing through a bot's key.

## 4. Open the PR as the bot (inline-override path)

`gh` uses whichever account is marked active. Switch to the bot's
GitHub user for the PR-creation call, then switch back to the
maintainer's:

```bash
gh auth switch --user <bot-github-user>
gh pr create --base main --head <branch> \
  --title "<type>(<scope>): <subject>" \
  --body "$(cat <<'EOF'
[fill the PR template]
EOF
)"
gh auth switch --user <maintainer-github-user>
```

- Title mirrors the primary commit (Conventional-Commits-shaped).
- Fill
  [`.github/pull_request_template.md`](../../../.github/pull_request_template.md).
- Don't paste content from `CLAUDE.local.md` or any other
  maintainer-private source into the PR body.
- Agents never self-merge. Only `CODEOWNERS` merges an agent-authored
  PR.

## 5. Non-negotiables

- Never push to `main` directly.
- Never self-merge an agent PR.
- Never set `remote.origin.url` to a bot SSH alias as local config.
- Never reference private maintainer resources (internal URLs, Drive
  docs, Slack threads, internal services) in a PR visible on the
  public repo.

## 6. When a PR is blocked

- **Hook / CI failure**: investigate the underlying cause. Never use
  `--no-verify` to bypass.
- **Signature missing or wrong identity on the commit**: you almost
  certainly committed without the inline `-c` overrides. Re-run through
  the [`commit`](../commit/SKILL.md) skill; if the commit was pushed
  and not yet reviewed, force-push the corrected commit on the same
  branch.
- **Unexpected files in the diff**: probably machine-local state that
  was not gitignored. See the [`add-agent`](../add-agent/SKILL.md)
  skill's gitignore section — add the missing ignore rule in the same
  PR if it's a new agent, or a separate `chore:` PR otherwise.
