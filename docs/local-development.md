# Local Development

Run the package checks from the repository root:

```bash
python3 scripts/validate_framework_package.py
python3 -m unittest discover -s test -p "*.py"
python3 -m compileall -q .
```

To test the package with Hermes manually, use a local checkout:

```bash
hermes plugins install "$(pwd)" --enable --force
hermes plugins list
```

Then ask the agent for the Tinyhat joke or run the registered command if
the active Hermes surface exposes plugin commands.
