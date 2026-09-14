# Capabilities

Each folder owns one Tinyhat capability and keeps its tool implementation,
workers, and private helpers together.

- `contact_details/`: the Agent's managed phone number and email address.
- `credit/`: owner credit and Agent model-budget operations.
- `account_upgrade/`: individual owner upgrade drafts and human review buttons for Stripe Projects.
- `mail/`: the Agent's private Tinyhat mailbox.
- `google_workspace/`: Google connection, permission, app, and worker flows.
- `hats/`: Hat creation, installation, repositories, and private values.
- `local_app_sharing/`: loopback gateway and platform-owned preview sessions.
- `computer_desktop/`: thin platform client for owner desktop connections.
- `secrets/`: private credential listing and encrypted handoff.
- `slack/`: Slack connection and disconnect flows.

The root `tools.py` and `schemas.py` files remain thin Hermes adapter facades.
New product behavior belongs in the matching capability folder rather than in
the repository root.


## Computer channels

`tinyhat_channels` and the `tinyhat-connect-channel` skill connect an existing
Computer to Telegram, Slack, or both. Telegram uses a private 24-hour pairing
link/QR; Slack uses the Computer's public key and a private credentials file.
The platform retains encrypted credentials; the runtime applies them through
`configure_channels` without changing the owner, email, model or user files.
