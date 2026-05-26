#!/usr/bin/env python3
"""Validate repo-local development skill adapters."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REQUIRED_SKILLS = (
    "add-agent",
    "codex",
    "commit",
    "define-tests",
    "open-pr",
    "propose-roadmap",
    "release",
    "review",
    "review-changelog",
    "sharpen-skill",
    "update-guidance",
)
PARENT_ALIGNED_SKILLS = (
    "codex",
    "commit",
    "define-tests",
    "open-pr",
    "release",
    "review",
    "sharpen-skill",
)


def fail(message: str) -> None:
    print(f"dev-skills: {message}", file=sys.stderr)
    raise SystemExit(1)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parent_skill_root(root: Path) -> Path | None:
    env_parent = os.environ.get("TINYLOOP_PARENT_REPO")
    candidates = []
    if env_parent:
        candidates.append(Path(env_parent).expanduser())
    if len(root.parents) > 2:
        candidates.append(root.parents[2])
    for candidate in candidates:
        skill_root = candidate / ".agents" / "skills"
        if skill_root.is_dir():
            return skill_root
    return None


def frontmatter_name(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8")
    match = re.search(r"^name:\s*([A-Za-z0-9_-]+)\s*$", text, re.MULTILINE)
    if not match:
        fail(f"{skill_md} is missing frontmatter name")
    return match.group(1)


def main() -> None:
    root = repo_root()
    agents_dir = root / ".agents" / "skills"
    claude_dir = root / ".claude" / "skills"
    if not agents_dir.is_dir():
        fail(".agents/skills is missing")
    if not claude_dir.is_dir():
        fail(".claude/skills is missing")

    parent_root = parent_skill_root(root)
    for skill in REQUIRED_SKILLS:
        skill_md = agents_dir / skill / "SKILL.md"
        if not skill_md.is_file():
            fail(f"missing {skill_md.relative_to(root)}")
        if frontmatter_name(skill_md) != skill:
            fail(f"{skill_md.relative_to(root)} frontmatter name must be {skill!r}")

        adapter = claude_dir / skill
        expected = Path("..") / ".." / ".agents" / "skills" / skill
        if not adapter.is_symlink() or Path(os.readlink(adapter)) != expected:
            fail(f"{adapter.relative_to(root)} must symlink to {expected}")

        if (
            parent_root
            and skill in PARENT_ALIGNED_SKILLS
            and not (parent_root / skill / "SKILL.md").is_file()
        ):
            fail(f"parent skill is missing: {parent_root / skill / 'SKILL.md'}")

    if parent_root:
        print(f"dev-skills: ok (parent={parent_root})")
    else:
        print("dev-skills: ok (parent skill root not mounted; standalone mode)")


if __name__ == "__main__":
    main()
