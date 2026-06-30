---
name: tinyhat-private-secret
description: Start a secure Tinyhat secret entry flow. Use when the user asks to add, save, create, update, or connect an API key, token, password, credential, webhook secret, or other secret for this agent.
---

# Tinyhat Private Secret

Use this when the user wants to add a secret or credential to the
current Tinyhat-managed Computer.

Never ask the user to paste the secret value in chat. Start a secure
secret entry instead:

1. Pick a specific env-style name from the user's request. If the user
   says "my Exa API key", use `EXA_API_KEY`. If they say GitHub token,
   use `GITHUB_TOKEN`. If they say Stripe secret key, use
   `STRIPE_SECRET_KEY`.
2. Add a short plain-English description that helps the user remember
   why the secret exists.
3. Call `tinyhat_private_secret_handoff` with `name` and `description`.
4. Call the tool once. Let the returned message stand. Tinyhat already
   sends the secure button.

Do not use generic names such as `TINYHAT_SECRET`, `SECRET`, `API_KEY`,
`TOKEN`, `PASSWORD`, or `CREDENTIAL`. If the provider or purpose is not
clear enough to choose a meaningful name, ask one short clarification
question before starting secret entry.

Use these common names when they match the user request:

| User wording | Secret name |
| --- | --- |
| Exa API key | `EXA_API_KEY` |
| OpenRouter API key | `OPENROUTER_API_KEY` |
| OpenAI API key | `OPENAI_API_KEY` |
| Anthropic API key | `ANTHROPIC_API_KEY` |
| GitHub token | `GITHUB_TOKEN` |
| Stripe secret key | `STRIPE_SECRET_KEY` |
| Tavily API key | `TAVILY_API_KEY` |
| Firecrawl API key | `FIRECRAWL_API_KEY` |
| Telegram bot token | `TELEGRAM_BOT_TOKEN` |
| Slack bot token | `SLACK_BOT_TOKEN` |

The secure entry flow works like a device flow. This Computer creates a one-time
key pair. The Tinyhat page encrypts the secret in the user's browser
with the public key, and this Computer decrypts it with the temporary
private key. Tinyhat stores only encrypted ciphertext during the short
entry window.

If the entry window expires, ask the user whether to create a new secure
link. Do not reuse old links.

Keep the chat response short. Do not render a second message with a
button, a table, exact expiration timestamp, status field, raw URL, JSON
payload, or extra explanation. The button that Tinyhat already sent is
the main action.
