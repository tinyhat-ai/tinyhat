# Tinyhat Plugin Agent Guide

This repository is the public Tinyhat plugin package. `main` is Hermes-only.

## Boundaries

- Keep the runtime small. Runtime work belongs in
  `tinyloophub/tinyhat--runtimes--hermes`.
- Keep platform APIs in the Tinyloop backend. This repo should not carry
  private backend URLs, tokens, tenant data, or provisioning scripts.
- Keep skills framework-neutral whenever possible. Framework-specific
  loading belongs in adapter files such as `plugin.yaml` and
  `hermes.plugin.json`.
- Do not add legacy framework files to this repository. Additional frameworks
  will return later as separate adapters once the Hermes path is stable.

## Current Package Shape

- `plugin.yaml`: Hermes manifest.
- `__init__.py`: Hermes registration entrypoint.
- `hermes.plugin.json`: Tinyhat adapter metadata.
- `tools.py`, `schemas.py`, `platform.py`, and `context.py`: thin adapter and
  shared-platform facades kept at the root because Hermes loads them directly.
- `capabilities/`: product behavior grouped by user-facing capability. Keep
  workers and private helpers inside the capability that owns them; do not add
  new feature implementation files to the repository root.
- `capabilities/google_workspace/`: Google connection, permission, app, and
  detached worker flows.
- `capabilities/hats/`, `capabilities/secrets/`, and `capabilities/slack/`:
  larger multi-file capabilities with their helpers kept together.
- `capabilities/contact_details/`, `capabilities/credit/`, and
  `capabilities/mail/`: focused Agent identity, funding, and mailbox tools.
- `capabilities/local_app_sharing/`: the loopback-only HTTP viewer gateway,
  pinned per-Computer Cloudflare connector, and thin client for platform-owned
  tunnel and sharing-session APIs.
- `skills/tinyhat-tell-joke/SKILL.md`: deterministic joke proof.
- `skills/tinyhat-plugin-version/SKILL.md`: live plugin version proof.
- `skills/tinyhat-onboarding-greeting/SKILL.md`: one-shot first owner greeting after Computer setup.
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
- `skills/tinyhat-credit/SKILL.md`: owner balance, recent transactions, the
  Agent's current AI model budget, and adding an exact amount to that budget.
- `skills/tinyhat-contact-details/SKILL.md`: the Agent's assigned phone number
  and email address.
- `skills/tinyhat-local-app-sharing/SKILL.md`: short-lived Visuals for visual
  reports, charts, dashboards, explanations, and previews.
- `skills/tinyhat-agentphone/SKILL.md`: direct AgentPhone calls and text
  messages with Computer-local credentials and fixed safety boundaries around
  the provider's online instructions.
- `skills/tinyhat-mail/SKILL.md`: safe access to the Agent's private Tinyhat
  inbox, controlled plain-text sending when enabled, and bounded direct JMAP
  access for other non-send mailbox actions.
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
version change. Update `VERSION`, all listed live manifests, package metadata, and
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
