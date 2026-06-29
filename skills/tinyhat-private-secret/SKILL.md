---
name: tinyhat-private-secret
description: Start a private Tinyhat secret handoff. Use when the user asks to add, save, create, update, or connect an API key, token, password, credential, webhook secret, or other secret for this agent.
---

# Tinyhat Private Secret

Use this when the user wants to add a secret or credential to the
current Tinyhat-managed Computer.

Never ask the user to paste the secret value in chat. Start a private
handoff instead:

1. Pick an env-style name such as `OPENROUTER_API_KEY`, `GITHUB_TOKEN`,
   or `STRIPE_SECRET_KEY`.
2. Add a short plain-English description that helps the user remember
   why the secret exists.
3. Call `tinyhat_private_secret_handoff` with `name` and `description`.
4. Show the returned secure Mini App button/link and explain that the
   user has about five minutes to enter the value.

The handoff works like a device flow. This Computer creates a one-time
key pair. The Tinyhat page encrypts the secret in the user's browser
with the public key, and this Computer decrypts it with the temporary
private key. Tinyhat stores only encrypted ciphertext during the handoff.

If the handoff expires, ask the user whether to create a new secure
link. Do not reuse old links.

Keep the chat response short. The button is the main action.
