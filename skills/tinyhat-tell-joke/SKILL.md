---
name: tinyhat-tell-joke
description: Tell a short Tinyhat wiring-test joke. Use when the user asks for a joke, asks whether the Tinyhat plugin is installed, or wants a simple proof that framework-neutral Tinyhat skills are available.
---

# Tinyhat Tell Joke

Use this as the smallest possible Tinyhat plugin proof.

When the user asks for a joke or asks whether the Tinyhat plugin is
available, call the `tinyhat_tell_joke` tool. Pass a short `topic` only
when the user gave one.

Keep the response short. The point is not comedy; the point is proving
that a framework can discover this shared skill and call its adapter
tool.

Never ask the user to paste a secret value in chat. Never print a raw
platform link, signed link, private URL, backend URL, tenant token, or
machine-local path.
