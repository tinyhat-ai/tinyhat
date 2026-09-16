"""Authenticated link to session data that stays on the Computer."""

from urllib.parse import urlsplit

from ...platform import build_platform_client, computer_api_path
from ...tools import _telegram_credentials, _telegram_send_message


def button():
    client, authentication = build_platform_client()
    result = client.get_json(
        computer_api_path(authentication, "channels/sessions-link", version="v2")
    )
    url = result.get("url", "")
    parsed = urlsplit(url)
    if (
        (
            parsed.scheme != "https"
            and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})
        )
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Session link is unavailable.")
    return {"text": "Open sessions", "url": url}


def telegram_command(raw_args=""):
    try:
        token, chat_id = _telegram_credentials()
        result = _telegram_send_message(
            token=token,
            chat_id=chat_id,
            text="Your sessions",
            reply_markup={"inline_keyboard": [[button()]]},
        )
        if not result.get("ok"):
            raise ValueError("Session link is unavailable.")
        return ""  # The button is already the complete command response.
    except Exception:
        return "Open your Computer page to view sessions."
