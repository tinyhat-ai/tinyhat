---
name: tinyhat-plugin-version
description: Report the Tinyhat plugin version currently loaded in Hermes. Use when the user asks which Tinyhat plugin version is running, loaded, active, or available to this agent.
---

# Tinyhat Plugin Version

Use this when the user asks which Tinyhat plugin version is running in the
current Hermes agent.

Call the `tinyhat_plugin_version` tool. Then answer with the version from
the tool result. Keep the answer short and say that this is the plugin code
loaded by Hermes for this agent.

Never infer the running plugin version from release notes, GitHub branches,
or admin metadata. The purpose of this skill is to prove the live plugin
that Hermes is actually using.
