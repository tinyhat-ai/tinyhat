# Capabilities

Each folder owns one Tinyhat capability and keeps its tool implementation,
workers, and private helpers together.

- `contact_details/`: the Agent's managed phone number and email address.
- `credit/`: owner credit and Agent model-budget operations.
- `mail/`: the Agent's private Tinyhat mailbox.
- `google_workspace/`: Google connection, permission, app, and worker flows.
- `hats/`: Hat creation, installation, repositories, and private values.
- `local_app_sharing/`: loopback gateway and platform-owned preview sessions.
- `secrets/`: private credential listing and encrypted handoff.
- `slack/`: Slack connection and disconnect flows.

The root `tools.py` and `schemas.py` files remain thin Hermes adapter facades.
New product behavior belongs in the matching capability folder rather than in
the repository root.
