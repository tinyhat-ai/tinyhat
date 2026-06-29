# Tinyhat Plugin Agent Guide

This repository is the public Tinyhat plugin package. The v0.20 branch is
a fresh Hermes-only start.

## Boundaries

- Keep the runtime small. Runtime work belongs in
  `tinyloophub/tinyhat--runtimes--hermes`.
- Keep platform APIs in the Tinyloop backend. This repo should not carry
  private backend URLs, tokens, tenant data, or provisioning scripts.
- Keep skills framework-neutral whenever possible. Framework-specific
  loading belongs in adapter files such as `plugin.yaml` and
  `hermes.plugin.json`.
- Do not add legacy framework files to this branch. Additional frameworks
  will return later as separate adapters once the Hermes path is stable.

## Current Package Shape

- `plugin.yaml`: Hermes manifest.
- `__init__.py`: Hermes registration entrypoint.
- `hermes.plugin.json`: Tinyhat adapter metadata.
- `tools.py` and `schemas.py`: tiny public tool surface.
- `skills/tinyhat-tell-joke/SKILL.md`: deterministic joke proof.
- `skills/tinyhat-plugin-version/SKILL.md`: live plugin version proof.

## Checks

Run these before committing:

```bash
python3 scripts/validate_framework_package.py
python3 -m unittest discover -s test -p "*.py"
python3 -m compileall -q .
```

## Writing

Use simple public language. The README is part of the trust surface: it
should explain what the plugin does, what it does not do, and why the
runtime/plugin boundary exists.
