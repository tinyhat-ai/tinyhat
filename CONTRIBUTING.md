# Contributing

This branch is intentionally small. Keep changes focused and public.

Before opening a pull request, run:

```bash
python3 scripts/validate_framework_package.py
python3 -m unittest discover -s test -p "*.py"
python3 -m compileall -q .
```

Do not include credentials, private platform URLs, local machine paths, or
tenant-specific examples. Do not add legacy framework adapter files to
this branch yet.
