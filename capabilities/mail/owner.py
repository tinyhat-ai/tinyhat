"""Assignment-authenticated owner mail; submission has no recipient parameter."""

import json
from urllib.parse import quote

from ...platform import PlatformError, build_platform_client
from ...tool_errors import tool_error_json

PREFIX = "/hapi/v2/computers/me/email"


def request(action, payload=None):
    client, _ = build_platform_client(timeout_seconds=45)
    if action == "status":
        return client.get_json(PREFIX)
    if action.startswith("deliveries/"):
        return client.get_json(PREFIX + "/deliveries/" + quote(action.split("/", 1)[1], safe=""))
    return client.post_json(PREFIX + "/" + action, payload or {})


def email_address(args=None, **_):
    args = args or {}
    try:
        action = args.get("action", "status")
        if action == "status":
            result = request("status")
        elif action == "prepare":
            result = request("rename", {"local_part": args.get("local_part")})
        elif (
            action == "confirm" and args.get("acknowledge_old_address_expires_in_24_hours") is True
        ):
            result = request(
                "rename/confirm",
                {
                    "confirmation_token": args.get("confirmation_token"),
                    "acknowledge_old_address_expires_in_24_hours": True,
                },
            )
        else:
            raise ValueError(
                "Choose status, prepare, or confirm after the owner approves the 24-hour notice."
            )
        return json.dumps(result)
    except (ValueError, PlatformError):
        return tool_error_json(
            tool="tinyhat_email_address",
            error_name="email_address_unavailable",
            message="The email change could not complete. Check status and try again after any limit expires.",
        )


def send_owner(args):
    channel = request("status")
    owner = channel["owner_email"].lower()
    recipients = args.get("to", [])
    if isinstance(recipients, str):
        recipients = [recipients]
    if recipients != [] and [str(value).lower() for value in recipients] != [owner]:
        raise ValueError("This email channel can send only to its verified owner.")
    if args.get("cc") or args.get("bcc") or args.get("attachments"):
        raise ValueError("Additional recipients and attachments are not supported by owner email.")
    return request(
        "send",
        {
            "subject": args.get("subject"),
            "body": args.get("body"),
            "idempotency_key": args.get("idempotency_key"),
        },
    )
