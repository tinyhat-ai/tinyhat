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
- `tools.py`, `schemas.py`, `platform.py`, `secret_handoff.py`,
  `google_workspace.py`, `google_workspace_app.py`, and
  `google_workspace_app_manager.py`: tiny public tool surface.
- `google_workspace_worker.py` and `google_workspace_disconnect_worker.py`:
  detached owner-bound connection and disconnect workers.
- `skills/tinyhat-tell-joke/SKILL.md`: deterministic joke proof.
- `skills/tinyhat-plugin-version/SKILL.md`: live plugin version proof.
- `skills/tinyhat-skill-catalog/SKILL.md`: plugin-qualified skill discovery.
- `skills/tinyhat-skill-authoring/SKILL.md`: customer-facing best practices for
  creating and revising portable Agent Skills, including trigger boundaries and
  context limits.
- `skills/tinyhat-private-secret/SKILL.md`: private Mini App secret handoff.
- `skills/tinyhat-credentials/SKILL.md`: value-blind credential discovery and confirmed Computer-side removal.
- `skills/tinyhat-google-workspace/SKILL.md`: multiple Google Workspace accounts, recommended/legacy/custom permissions, and account-targeted disconnect.
- `skills/tinyhat-google-workspace-app-manager/SKILL.md`: confirmed pinned gws binary manager; Hermes supplies operation guidance.
- `skills/tinyhat-codex-auth/SKILL.md`: OpenAI Codex / ChatGPT subscription auth flow guidance.
- `skills/tinyhat-plugin-update/SKILL.md`: installed plugin channel update guidance.
- `skills/tinyhat-platform/SKILL.md`: Tinyhat-managed Hermes operating context.
- `skills/tinyhat-privacy/SKILL.md`: privacy and trust model answers for who-can-see-my-data questions.
- `context.py`: small keyword-gated Hermes `pre_llm_call` context hook.
- `.agents/skills/tinyhat-plugin-skill-authoring/SKILL.md`: maintainer
  workflow for adding or changing plugin skills.

## Checks

Run these before committing:

```bash
python3 scripts/validate_framework_package.py
python3 -m unittest discover -s test -p "*.py"
python3 -m compileall -q .
```

When adding or changing plugin skills, read
`.agents/skills/tinyhat-plugin-skill-authoring/SKILL.md` first.

## Version Bumps

Follow `RELEASING.md` section **Version Bump Checklist** for every plugin
version change. Update all listed live manifests, package metadata, and
adapter-test expectations in the same PR. Do not assume the loader manifest
is the running-version source: `tinyhat_plugin_version` and the
`/tinyhat-plugin-version` command report the `version` field from
`hermes.plugin.json`.

Run the package validator, full unittest suite, and `compileall` before
promoting a version. Read back `hermes.plugin.json` from each promoted channel
to verify the live command will report the intended version.

## Writing

Use simple public language. The README is part of the trust surface: it
should explain what the plugin does, what it does not do, and why the
runtime/plugin boundary exists.
