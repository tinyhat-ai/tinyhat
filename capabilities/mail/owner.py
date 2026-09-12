"""Assignment-authenticated owner mail; submission has no recipient parameter."""

import contextlib
import json
import re
from http import HTTPStatus
from urllib.error import HTTPError
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


def error_details(exc):
    """Expose bounded public error codes, never provider bodies or credentials."""
    detail = (exc.response or {}).get("error", {})
    if not isinstance(detail, dict):
        detail = {}
    code = detail.get("code", "email_service_unavailable")
    if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
        code = "email_service_unavailable"
    delay = detail.get("retry_after", 60)
    if isinstance(exc.__cause__, HTTPError):
        with contextlib.suppress(ValueError, TypeError, AttributeError):
            delay = int(exc.__cause__.headers.get("Retry-After", delay))
    if not isinstance(delay, int) or isinstance(delay, bool):
        delay = 60
    return code, max(60, min(delay, 86400))


def platform_error_json(tool, exc):
    code, delay = error_details(exc)
    return tool_error_json(
        tool=tool,
        error_name=code,
        message="Tinyhat could not complete this email operation. Check its status before retrying.",
        expected={"retry_after_seconds": delay}
        if exc.status_code == HTTPStatus.TOO_MANY_REQUESTS
        else None,
    )


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
    except PlatformError as exc:
        return platform_error_json("tinyhat_email_address", exc)
    except ValueError:
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
