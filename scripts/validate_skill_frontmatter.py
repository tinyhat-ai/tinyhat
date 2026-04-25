#!/usr/bin/env python3
"""Validate every SKILL.md frontmatter against Tinyhat's header policy.

Policy lives at ``.claude/skills/update-guidance/references/skill-frontmatter.md``.
This script enforces the machine-checkable parts so a header that drifts
past the policy fails CI.

Stdlib only — the validator must run in the smoke matrix (Python 3.9, 3.11,
3.12 on Ubuntu and macOS) without an extra ``pip install`` step, matching
the "stdlib only" stance in ``pyproject.toml``.

Exit 0 on a clean tree, 1 on any policy violation. With ``--fix`` it would
attempt automatic repairs, but no auto-fix exists yet — every violation in
the current tree was a one-time backfill landed in the same PR that added
this script.

Usage::

    python3 scripts/validate_skill_frontmatter.py                # repo root
    python3 scripts/validate_skill_frontmatter.py path/to/SKILL.md ...
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Anthropic's published constraints on `name` and `description`. Mirrored from
# https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
# and https://agentskills.io/specification.
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_MAX_LEN = 64
NAME_FORBIDDEN_SUBSTRINGS = ("anthropic", "claude")
DESCRIPTION_MAX_LEN = 1024

# gbrain ships these as top-level keys; Claude Code does not parse them.
# Tinyhat rejects them at the top level — see the policy reference for the
# per-key reasoning. Use ``metadata.*`` for genuine extension keys.
DISALLOWED_TOP_LEVEL_KEYS = (
    "triggers",
    "tools",
    "mutating",
    "version",
    "writes_pages",
    "writes_to",
)

# Top-level keys Tinyhat policy treats as known-good. Anything else is
# warned (not failed) so a future Claude Code addition is surfaced for
# review without breaking the build.
KNOWN_TOP_LEVEL_KEYS = frozenset(
    {
        "name",
        "description",
        "when_to_use",
        "argument-hint",
        "arguments",
        "allowed-tools",
        "disable-model-invocation",
        "user-invocable",
        "model",
        "effort",
        "context",
        "agent",
        "hooks",
        "paths",
        "shell",
        "license",
        "compatibility",
        "metadata",
    }
)


def _find_skill_files(roots: list[Path]) -> list[Path]:
    """Discover every ``SKILL.md`` under the given roots."""
    found: list[Path] = []
    for root in roots:
        if root.is_file():
            found.append(root)
            continue
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("SKILL.md")):
            # Ignore nested worktrees that sit under the scan root, but not
            # the worktree we're scanning *from* (the absolute path always
            # contains ".claude/worktrees" in that case).
            try:
                relative = path.relative_to(root)
            except ValueError:
                relative = path
            if ".claude/worktrees" in relative.as_posix():
                continue
            found.append(path)
    return found


def _extract_frontmatter(text: str) -> tuple[str, int] | None:
    """Return the YAML frontmatter block and the line number it ends on.

    Returns ``None`` if the file does not start with a ``---`` fence.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return ("\n".join(lines[1:idx]), idx + 1)
    return None


# Minimal YAML reader for the bounded shape SKILL.md frontmatter actually
# uses. We only need to enumerate top-level keys and read the string value
# of ``name`` + ``description``. A full YAML parser would pull pyyaml as
# a dependency; the SKILL.md surface is small enough to hand-parse.
_KEY_LINE_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$")


def _parse_top_level_keys(block: str) -> dict[str, str | None]:
    """Return ``{key: scalar_or_None}`` for top-level keys in the block.

    A scalar value is the raw text after the colon (whitespace-stripped).
    A key with a list / block / nested-mapping value is returned as ``None``
    — that is enough for the checks this script needs to perform.
    """
    keys: dict[str, str | None] = {}
    for line in block.splitlines():
        if not line or line.startswith("#"):
            continue
        # A top-level key starts at column 0; nested keys are indented.
        if line[0] in (" ", "\t"):
            continue
        match = _KEY_LINE_RE.match(line)
        if not match:
            continue
        key, raw_value = match.group(1), match.group(2).strip()
        if not raw_value or raw_value in ("|", ">"):
            keys[key] = None
        else:
            keys[key] = _strip_quotes(raw_value)
    return keys


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _check_skill(path: Path) -> list[str]:
    """Return a list of human-readable violation strings; empty == clean."""
    violations: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: cannot read file ({exc})"]

    extracted = _extract_frontmatter(text)
    if extracted is None:
        violations.append(f"{path}: missing YAML frontmatter (expected '---' at line 1)")
        return violations

    block, _ = extracted
    keys = _parse_top_level_keys(block)

    # 1. Required keys.
    for required in ("name", "description"):
        if required not in keys:
            violations.append(f"{path}: missing required frontmatter key `{required}`")

    # 2. Disallowed gbrain-style top-level keys.
    for bad in DISALLOWED_TOP_LEVEL_KEYS:
        if bad in keys:
            violations.append(
                f"{path}: top-level key `{bad}` is rejected by Tinyhat policy "
                f"(see references/skill-frontmatter.md). Move under `metadata.*` "
                f"if a custom field is genuinely needed."
            )

    # 3. Unknown keys → warning, not failure (surface in stderr but exit 0).
    unknown = sorted(set(keys) - KNOWN_TOP_LEVEL_KEYS - set(DISALLOWED_TOP_LEVEL_KEYS))
    for key in unknown:
        print(
            f"{path}: warning — unrecognized top-level key `{key}`. "
            f"If this is a Claude Code addition, update KNOWN_TOP_LEVEL_KEYS "
            f"in {Path(__file__).name}.",
            file=sys.stderr,
        )

    # 4. `name` shape + directory match.
    name = keys.get("name")
    if name is not None:
        if name is None or name == "":
            violations.append(f"{path}: `name` is empty")
        elif len(name) > NAME_MAX_LEN:
            violations.append(f"{path}: `name` exceeds {NAME_MAX_LEN} chars (got {len(name)})")
        elif not NAME_RE.match(name):
            violations.append(
                f"{path}: `name` must match {NAME_RE.pattern} "
                f"(lowercase letters/digits/hyphens, no leading/trailing hyphen). Got: {name!r}"
            )
        else:
            for forbidden in NAME_FORBIDDEN_SUBSTRINGS:
                if forbidden in name:
                    violations.append(f"{path}: `name` cannot contain {forbidden!r}")
            expected_dir = path.parent.name
            if name != expected_dir:
                violations.append(
                    f"{path}: `name: {name}` must equal the parent directory name `{expected_dir}`"
                )

    # 5. `description` length.
    description = keys.get("description")
    if isinstance(description, str) and len(description) > DESCRIPTION_MAX_LEN:
        violations.append(
            f"{path}: `description` exceeds {DESCRIPTION_MAX_LEN} chars (got {len(description)})"
        )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="SKILL.md files or directories to scan. Defaults to .claude/skills and skills.",
    )
    args = parser.parse_args(argv)

    if args.paths:
        roots = args.paths
    else:
        repo_root = Path(__file__).resolve().parent.parent
        roots = [repo_root / ".claude" / "skills", repo_root / "skills"]

    skill_files = _find_skill_files(roots)
    if not skill_files:
        print("validate_skill_frontmatter: no SKILL.md files found", file=sys.stderr)
        return 0

    all_violations: list[str] = []
    for path in skill_files:
        all_violations.extend(_check_skill(path))

    if all_violations:
        for line in all_violations:
            print(line, file=sys.stderr)
        print(
            f"\nvalidate_skill_frontmatter: {len(all_violations)} violation(s) "
            f"across {len(skill_files)} SKILL.md file(s).",
            file=sys.stderr,
        )
        return 1

    print(f"validate_skill_frontmatter: ok ({len(skill_files)} SKILL.md files clean).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
