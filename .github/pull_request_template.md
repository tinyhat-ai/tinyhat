## Summary

<!-- What changed and why. One or two sentences. -->

## Testing Performed

- [ ] `git diff --check`
- [ ] `bash .github/scripts/check_packaging.sh`
- [ ] `python3 scripts/validate_framework_package.py`
- [ ] `python3 -m unittest discover -s test -p "*.py"`
- [ ] `python3 -m compileall -q .`

## Checklist

- [ ] Docs updated where behavior changed.
- [ ] Packaged skill changes follow `docs/skill-authoring.md`.
- [ ] No tenant secrets, signed links, private backend URLs, local-only
      paths, or internal docs are included.
- [ ] I will not self-merge.
