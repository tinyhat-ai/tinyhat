"""Lazy gateway registration keeps ordinary Tinyhat tools framework neutral."""

import os


def build_adapter(config):
    from .channel import TinyhatEmailAdapter

    return TinyhatEmailAdapter(config)


def register(ctx):
    ctx.register_platform(
        name="tinyhat_email",
        label="Tinyhat email",
        adapter_factory=build_adapter,
        check_fn=lambda: True,
        allowed_users_env="TINYHAT_EMAIL_OWNER",
        max_message_length=20_000,
        env_enablement_fn=lambda: (
            {"enabled": True} if os.environ.get("TINYHAT_EMAIL_CHANNEL_ENABLED") == "1" else None
        ),
        pii_safe=True,
        allow_update_command=False,
        platform_hint="Write short plain-text email replies. The transport sends only to the owner.",
    )
