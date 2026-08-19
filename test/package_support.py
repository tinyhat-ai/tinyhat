"""Load this checkout as the ``tinyhat`` package from arbitrarily named worktrees."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_local_tinyhat(repo_root: Path) -> None:
    """Make capability imports resolve to this checkout during tests."""
    if repo_root.name == "tinyhat":
        return
    spec = importlib.util.spec_from_file_location(
        "tinyhat",
        repo_root / "__init__.py",
        submodule_search_locations=[str(repo_root)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load local tinyhat package for tests.")
    package = importlib.util.module_from_spec(spec)
    sys.modules["tinyhat"] = package
    spec.loader.exec_module(package)
