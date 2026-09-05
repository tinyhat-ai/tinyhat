# Contributing

Keep each commit focused on one logical change and each PR on one related
thread. Work from a separate worktree and a feature branch; never push directly
to `main`, self-approve, or self-merge. Follow machine-local agent identity and
signing instructions when present, without changing the maintainer's Git or
GitHub settings. Restore any changed GitHub CLI account after a write.

Before committing and before opening a pull request, run from the repository
root with the project Python environment:

```bash
git diff --check
python3 scripts/validate_framework_package.py
python3 -m unittest discover -s test -p "*.py"
python3 -m compileall -q .
```

Fix failures before proceeding; do not bypass hooks or suppress failing checks.
The package validator, unittest suite, and compile check are the checks used by
[CI](.github/workflows/ci.yml).

In the PR, explain the behavior changed, why, and what was verified. Obtain an
independent review of the current PR head and pass required checks before merge;
after changes, refresh the review against the new head. Report local validation,
CI, release publication, and channel promotion as separate results. Release and
channel changes must follow [RELEASING.md](RELEASING.md).

Do not include credentials, private platform URLs, local machine paths, or
tenant-specific examples. Do not add legacy framework adapter files to
this branch.
