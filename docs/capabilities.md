# Tinyhat Platform Capabilities

This package exposes a small public contract for Tinyhat-managed
OpenClaw Computers.
The contract names capabilities and tools; it does not teach agents to
call raw Tinyhat backend URLs.

## Operation Table

| Operation | Tool | Input | Output policy |
| --- | --- | --- | --- |
| `credentials.open_add_secret` | `tinyhat_request_runtime_secret` | `name`, optional `description` | Safe copy plus Telegram button transport; no secret values or raw URL prose. |
| `credentials.list_metadata` | `tinyhat_list_runtime_secrets` | none | Secret names/descriptions/status only; Manage Secrets button transport when available. |
| `computer.open_manage` | `tinyhat_open_manage_computer_link` | none | Safe copy plus Telegram button transport. |
| `computer.open_terminal` | `tinyhat_open_terminal_link` | optional admin-reviewed `command` | Safe copy plus Telegram button transport. |
| `computer.status` | `tinyhat_get_platform_status` | none | Secret-free status and platform contract. |
| `packages.list_installed` | `tinyhat_list_installed_packages` | none | Public package refs/SHAs and Tinyhat/user split when available. |
| `support.report_problem` | `tinyhat_report_problem` | optional summary | Redacted support context. |

## Default Skill Layer

The default skill layer uses one router plus focused skills:

| Skill | Primary operations |
| --- | --- |
| `tinyhat-platform` | Routes broad user intent to the focused skills below. |
| `tinyhat-secrets` | `credentials.open_add_secret`, `credentials.list_metadata`. |
| `tinyhat-computer-access` | `computer.open_manage`, `computer.open_terminal`. |
| `tinyhat-runtime-status` | `computer.status` and the no-generic-restart boundary. |
| `tinyhat-package-inventory` | `packages.list_installed`. |
| `tinyhat-support-report` | `support.report_problem`. |

Skills call named tools or documented operation identifiers.
They must not call raw Tinyhat backend paths.

## Secret Entry

Secret entry is a user action, not an agent-readable value.
The agent supplies a non-secret name such as `OPENAI_API_KEY` and a
short description.
Tinyhat returns a Telegram Mini App button payload.
The user enters the value inside Telegram, and the agent never receives
the value.

If a tool response contains a raw Mini App URL inside Telegram
`channelData` for transport reasons, skills must not paste that URL
into chat.
The only user-facing representation is the safe `text` copy and the
structured Telegram button.

## Runtime Boundary

The runtime/bootstrap package may install or pin this plugin, but it
does not own the Tinyhat capability behavior.
This repository owns the OpenClaw plugin manifest, tool names,
capability descriptions, default skills, and public release metadata.

## Public Safety

Do not add tenant secrets, signed intent tokens, private Tinyhat URLs,
local development paths, or private docs to package metadata, skills,
or issue/PR text.
