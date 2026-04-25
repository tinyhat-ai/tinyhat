#!/usr/bin/env python3
"""Lint every SKILL.md under skills/ and .claude/skills/.

Hard rules (exit 1):
  - Frontmatter is well-formed YAML-ish (`---` block at top).
  - `description` field present and non-empty.
  - `description` <= 1024 characters (Anthropic Agent Skills standard).
  - `name`, when present, matches the directory name, is <= 64
    characters, lowercase + digits + hyphens only, and does not
    contain the reserved words "anthropic" or "claude".
  - SKILL.md body <= 500 lines (Anthropic best-practices ceiling).

Soft rules (printed as warnings, do NOT fail CI yet):
  - SKILL.md body has a `## Gotchas` (or equivalent) section. Tracked
    under the skill-authoring touch-up sweep; promote to a hard rule
    once every skill has one.
  - `allowed-tools`, when present, is path-scoped (no bare `Bash(*)`,
    no bare `Bash(python3 *)`, no bare `Read`/`Write`). Tracked under
    issue #18; promote to a hard rule once that sweep lands.

Reference: docs/skill-authoring.md.

Dependency-free; runs on any Python 3.9+ on macOS or Linux.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

# Sections we treat as Gotchas-equivalent.
GOTCHA_SECTION_RE = re.compile(
    r"^##\s+(?:\d+\.\s+)?(Gotchas|Common pitfalls|Anti-Patterns|"
    r"Anti-patterns|Common Mistakes|Common Issues|Non-negotiables|"
    r"Red Flags)\b",
    re.M | re.I,
)

NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
RESERVED_NAME_TOKENS = ("anthropic", "claude")

BARE_BASH_GLOB_RE = re.compile(
    r"\bBash\(\s*(?:\*|[a-z][a-z0-9_-]*\s+\*)\s*\)",
    re.I,
)


def find_skills() -> list[pathlib.Path]:
    return sorted(
        list(REPO_ROOT.glob("skills/*/SKILL.md"))
        + list(REPO_ROOT.glob(".claude/skills/*/SKILL.md"))
    )


def parse_frontmatter(text: str) -> tuple[str, str] | None:
    """Return (frontmatter_block, body) or None if no `---` block found."""
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return None
    return m.group(1), text[m.end() :]


def get_field(fm: str, key: str) -> str | None:
    """Tiny YAML-ish field reader: matches `key: value` (single-line) and
    `key: |` / `key: >` block scalars (folded/literal). Returns the
    stripped value, or None if missing.

    We deliberately avoid pulling in PyYAML so the lint runs in any
    Python 3.9+ on stock CI without an install step.
    """
    block_m = re.search(rf"^{re.escape(key)}:\s*([|>])\s*\n((?:[ \t]+.+\n?)+)", fm, re.M)
    if block_m:
        indented = block_m.group(2)
        lines = [ln.lstrip() for ln in indented.splitlines()]
        return " ".join(line for line in lines if line)

    line_m = re.search(rf"^{re.escape(key)}:\s*(.+)$", fm, re.M)
    if line_m:
        return line_m.group(1).strip()
    return None


def lint_one(path: pathlib.Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one SKILL.md."""
    errors: list[str] = []
    warnings: list[str] = []

    text = path.read_text()
    parsed = parse_frontmatter(text)
    if parsed is None:
        errors.append("missing or malformed YAML frontmatter (`---` block)")
        return errors, warnings

    fm, body = parsed

    # --- description --------------------------------------------------
    description = get_field(fm, "description")
    if not description:
        errors.append(
            "frontmatter `description` is required (recommended by Claude Code; required by the open Agent Skills standard)"
        )
    elif len(description) > 1024:
        errors.append(
            f"`description` is {len(description)} chars; Anthropic caps at 1024 — see docs/skill-authoring.md §3"
        )

    # --- name (optional) ----------------------------------------------
    name = get_field(fm, "name")
    dir_name = path.parent.name
    if name is not None:
        if name != dir_name:
            errors.append(f"`name: {name}` does not match directory `{dir_name}` — pick one")
        if not NAME_RE.match(name):
            errors.append(f"`name: {name}` must be lowercase letters/digits/hyphens, max 64 chars")
        if any(tok in name for tok in RESERVED_NAME_TOKENS):
            errors.append(f"`name: {name}` contains a reserved word ({RESERVED_NAME_TOKENS!r})")

    # --- body length --------------------------------------------------
    body_lines = body.count("\n") + 1
    if body_lines > 500:
        errors.append(
            f"body is {body_lines} lines; Anthropic's hard ceiling is 500 — split into references/"
        )

    # --- soft: Gotchas section ----------------------------------------
    if not GOTCHA_SECTION_RE.search(body):
        warnings.append(
            "no `## Gotchas` (or equivalent: Anti-Patterns, Common Mistakes, Non-negotiables) section — see docs/skill-authoring.md §11"
        )

    # --- soft: allowed-tools path-scoping -----------------------------
    allowed_tools = get_field(fm, "allowed-tools")
    if allowed_tools and BARE_BASH_GLOB_RE.search(allowed_tools):
        warnings.append(
            "`allowed-tools` contains a bare Bash glob — path-scope per docs/skill-authoring.md §7 (issue #18)"
        )

    return errors, warnings


def main() -> int:
    skills = find_skills()
    if not skills:
        print("lint_skills: no SKILL.md files found", file=sys.stderr)
        return 1

    total_errors = 0
    total_warnings = 0
    for path in skills:
        errors, warnings = lint_one(path)
        rel = path.relative_to(REPO_ROOT)
        if errors or warnings:
            print(f"\n{rel}")
            for e in errors:
                print(f"  ERROR: {e}")
            for w in warnings:
                print(f"  warn:  {w}")
        total_errors += len(errors)
        total_warnings += len(warnings)

    print(
        f"\nlint_skills: {len(skills)} SKILL.md files; "
        f"{total_errors} error(s), {total_warnings} warning(s)"
    )

    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
