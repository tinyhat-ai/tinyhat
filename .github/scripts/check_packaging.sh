#!/usr/bin/env bash
# Fails CI if dev-only assets (the dev-reset skill, its helper script) leak
# into the paths a `/plugin install` would expose to end users. See #55.
#
# The rules we enforce:
#
#   1. `skills/dev-reset/` must not exist — plugin-scoped skills live under
#      `skills/`; the dev-reset skill is repo-scoped and belongs under
#      `.claude/skills/dev-reset/`.
#   2. No file under `skills/` or `.claude-plugin/` may reference the
#      dev-reset helper script by name.
#   3. The repo-scoped SKILL.md must exist and its description must start
#      with "INTERNAL DEV ONLY" so any skill listing makes the intent
#      obvious.
#   4. The helper script must exist (otherwise the skill is broken).
#
# Keep this script dependency-free so it runs identically on any Ubuntu or
# macOS GitHub runner without extra setup.

set -euo pipefail

fail() {
  echo "packaging-guard: $*" >&2
  exit 1
}

# 1. Plugin-scoped path must not hold the dev-reset skill.
if [[ -e skills/dev-reset ]]; then
  fail "skills/dev-reset/ must not exist — move it to .claude/skills/dev-reset/"
fi

# 2. Packaged plugin files must not mention the dev-reset helper.
if grep -r -l -E 'dev[-_]reset' skills/ .claude-plugin/ 2>/dev/null; then
  fail "packaged plugin files above reference dev-reset — must be repo-scoped only"
fi

# 3. Repo-scoped SKILL.md exists and advertises its intent.
skill_md=".claude/skills/dev-reset/SKILL.md"
[[ -f "$skill_md" ]] || fail "$skill_md is missing"
if ! grep -qE '^description: INTERNAL DEV ONLY' "$skill_md"; then
  fail "$skill_md frontmatter description must start with 'INTERNAL DEV ONLY'"
fi

# 4. Helper script exists.
[[ -f scripts/dev_reset.py ]] || fail "scripts/dev_reset.py is missing"

echo "packaging-guard: ok"
