#!/usr/bin/env bash
# Fails CI if legacy plugin surfaces leak into the fresh Hermes branch.

set -euo pipefail

fail() {
  echo "packaging-guard: $*" >&2
  exit 1
}

[[ -f plugin.yaml ]] || fail "plugin.yaml is missing"
[[ -f hermes.plugin.json ]] || fail "hermes.plugin.json is missing"
[[ -f __init__.py ]] || fail "__init__.py is missing"
[[ -f schemas.py ]] || fail "schemas.py is missing"
[[ -f tools.py ]] || fail "tools.py is missing"
[[ -d skills/tinyhat-tell-joke ]] || fail "tinyhat-tell-joke skill is missing"

for forbidden in openclaw.plugin.json src .claude .agents; do
  if [[ -e "$forbidden" ]]; then
    fail "$forbidden must not exist in the fresh Hermes plugin branch"
  fi
done

if find skills -mindepth 1 -maxdepth 1 -type d ! -name tinyhat-tell-joke | grep -q .; then
  fail "only tinyhat-tell-joke may ship in this first branch"
fi

if grep -R -n -E 'CLAUDE_PLUGIN_DATA|ChatGPT subscription|Mini App URL' \
  README.md AGENTS.md CONTRIBUTING.md RELEASING.md docs skills plugin.yaml hermes.plugin.json \
  __init__.py schemas.py tools.py test 2>/dev/null; then
  fail "fresh public surfaces still reference legacy plugin concepts"
fi

echo "packaging-guard: ok"
