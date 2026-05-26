#!/usr/bin/env bash
# Fails CI if repo-local development assets leak into the packaged
# OpenClaw plugin surface.

set -euo pipefail

fail() {
  echo "packaging-guard: $*" >&2
  exit 1
}

[[ -f openclaw.plugin.json ]] || fail "openclaw.plugin.json is missing"
[[ -f package.json ]] || fail "package.json is missing"
[[ -f src/index.js ]] || fail "src/index.js is missing"
[[ -d skills ]] || fail "skills/ is missing"

if [[ -e .claude-plugin ]]; then
  fail ".claude-plugin/ must not exist in the OpenClaw plugin package"
fi

if find skills -maxdepth 2 -type f -name 'SKILL.md' | grep -q '.agents'; then
  fail "packaged skills must live under skills/, not .agents/"
fi

if find skills -path '*/dev-reset/*' -o -name 'dev_reset.py' | grep -q .; then
  fail "dev-reset assets must not be packaged"
fi

if grep -r -l -E 'gather_snapshot|render_report|tinyhat-snapshot|CLAUDE_PLUGIN_DATA|skill-audit' \
  README.md openclaw.plugin.json package.json docs skills src 2>/dev/null; then
  fail "packaged/public surfaces reference the retired audit plugin"
fi

echo "packaging-guard: ok"
