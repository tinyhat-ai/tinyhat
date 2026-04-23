#!/usr/bin/env bash
# Every `python3` invocation inside a packaged `skills/**/SKILL.md` must be
# prefixed with `CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}"` — Claude Code
# expands `${CLAUDE_PLUGIN_DATA}` in the rendered skill body but does not
# export it into the Bash-tool environment, so scripts that rely on the env
# var see an empty value unless we forward it explicitly. See issue #58.
#
# This lint stays a plain shell script so it runs identically on any Ubuntu
# or macOS GitHub runner without extra setup.

set -euo pipefail

fail() {
  echo "skill-env-passthrough: $*" >&2
  exit 1
}

violations=0

while IFS= read -r -d '' skill_md; do
  # Match lines that start a `python3` call — either bare or behind a
  # simple indent (e.g. a nested bullet). Skip comment lines.
  #
  # A compliant line looks like:
  #   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" python3 ...
  while IFS=: read -r lineno content; do
    # Strip a single leading run of spaces (markdown indent) for the check.
    trimmed="${content#"${content%%[![:space:]]*}"}"
    # Ignore commented examples.
    case "$trimmed" in
      \#*) continue ;;
    esac
    case "$trimmed" in
      'CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" python3 '*) ;;
      python3' '*|python3)
        echo "  $skill_md:$lineno  $trimmed"
        violations=$((violations + 1))
        ;;
    esac
  done < <(grep -n -E '(^|[[:space:]])python3([[:space:]]|$)' "$skill_md" || true)
done < <(find skills -name SKILL.md -print0)

if [[ $violations -gt 0 ]]; then
  fail "$violations python3 invocation(s) missing the CLAUDE_PLUGIN_DATA passthrough prefix (see above)."
fi

echo "skill-env-passthrough: ok"
