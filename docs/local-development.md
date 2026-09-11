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

### Account review on separate API and web hosts

For account-upgrade tests, set `TINYHAT_ACCOUNT_REVIEW_ORIGIN` in the Computer's
runtime environment to the test frontend’s HTTPS origin. For example, API
`https://api.example.test` can return review links on `https://app.example.test`
when the latter is configured as the review origin. This is operator-provided
configuration, not a tool argument or an owner-provided URL. It does not bypass
owner email sign-in or final approval. Production needs no override.
