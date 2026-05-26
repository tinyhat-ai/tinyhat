# Local Development

This repository is an OpenClaw plugin package. Local checks focus on
package shape, manifest/tool consistency, public-safety boundaries, and
syntax.

## Prerequisites

- Python 3.9+.
- Node.js 18+.
- Optional: `ruff` via `pipx` or a local virtual environment.

## Fast Check Loop

```bash
git diff --check
python3 scripts/check_dev_skills.py
bash .github/scripts/check_packaging.sh
python3 scripts/validate_openclaw_package.py
python3 -m compileall -q scripts
node --check src/index.js
node --test
```

If `ruff` is available:

```bash
ruff check .
ruff format --check .
```

or:

```bash
pipx run ruff check .
pipx run ruff format --check .
```

## What The Checks Cover

| Check | Purpose |
| --- | --- |
| `scripts/check_dev_skills.py` | Ensures repo-local development skills and Claude adapters are wired. |
| `.github/scripts/check_packaging.sh` | Ensures dev-only skills stay out of packaged plugin surfaces. |
| `scripts/validate_openclaw_package.py` | Validates manifest/package/tool/skill consistency, packaged-skill authoring checks, and retired-artifact guards. |
| `node --check src/index.js` | Catches JavaScript syntax errors without needing OpenClaw installed. |
| `node --test` | Runs pure JavaScript safety tests for redaction and command parsing. |
| `ruff` | Lints and format-checks Python helper scripts. |

## Manual OpenClaw Smoke Test

Use an OpenClaw development instance when available:

```bash
openclaw plugins install "$(pwd)" --force
```

Then verify that OpenClaw sees:

- plugin id `tinyhat`;
- extension `./src/index.js`;
- packaged skills under `skills/`;
- tools listed in `openclaw.plugin.json` and `src/index.js`.

When testing against a local Tinyhat backend, pass development config
through the plugin/runtime environment rather than hard-coding private
URLs into this repo:

```bash
TINYHAT_PLATFORM_BASE_URL=http://127.0.0.1:8000
TINYHAT_DEV_RUNTIME=1
TINYHAT_DEV_BEARER=dev-runtime
```

Do not commit local endpoint values.

## Before Opening A PR

1. Fetch and branch from latest `origin/main`.
2. Run the fast check loop above.
3. Add docs when the capability contract changes.
4. Keep the PR focused on one concern.
5. Confirm no public file includes tenant secrets, signed URLs, private
   backend URLs, or local-only machine paths.
