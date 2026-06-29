# Security

Please report security issues privately instead of opening a public issue.

This repository should not contain:

- platform tokens or bot tokens;
- tenant-specific examples;
- private platform URLs;
- signed links;
- machine-local paths;
- secret values in prompts, tests, docs, or skill examples.

The plugin is agent-facing guidance and small adapter code. Platform
authorization lives in Tinyhat platform APIs, and Computer identity lives
in the Tinyhat runtime.

When reporting a vulnerability, include:

- the plugin commit or tag;
- the Hermes version if known;
- clear reproduction steps;
- redacted logs only.
