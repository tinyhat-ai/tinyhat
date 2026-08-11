"""Automatic, value-blind Hat credential transfer for runtime dispatch."""

from __future__ import annotations

from typing import Any

from .hat_secrets import (
    create_authenticated_hat_secret_envelope,
    credential_names_fingerprint_sha256,
    normalize_hat_handle,
    normalize_secret_name,
)
from .platform import PlatformError, build_platform_client, computer_api_path

RESULT_SCHEMA = "tinyhat_hat_credential_transfer_result_v1"


def complete_hat_credential_transfer(
    handoff_id: str, *, expected_hat_handle: str | None = None
) -> dict[str, Any]:
    """Prepare and submit one pre-authorized creator-to-consumer envelope.

    This function is called directly by the Tinyhat runtime.  It never invokes
    Hermes or asks the creator a question.  Its return value deliberately
    contains only identifiers, a count, and booleans; ciphertext and credential
    values stay outside the runtime command ledger.
    """

    clean_handoff_id = str(handoff_id or "").strip()
    if not clean_handoff_id:
        raise PlatformError("The Hat transfer handoff id is missing.")
    clean_expected_handle = (
        normalize_hat_handle(expected_hat_handle) if expected_hat_handle else None
    )
    client, platform_auth = build_platform_client()
    path = computer_api_path(platform_auth, "hats/v1")
    listed = client.get_json(f"{path}/credential-transfers")
    items = listed.get("items") if isinstance(listed, dict) else None
    if not isinstance(items, list):
        raise PlatformError("The platform returned invalid Hat transfer metadata.")
    matches = [
        item
        for item in items
        if isinstance(item, dict) and str(item.get("handoff_id") or "") == clean_handoff_id
    ]
    if len(matches) != 1:
        raise PlatformError("The requested Hat credential transfer is not pending.")
    transfer = matches[0]
    handle = normalize_hat_handle(str(transfer.get("hat_handle") or ""))
    if clean_expected_handle is not None and handle != clean_expected_handle:
        raise PlatformError("The requested transfer belongs to a different Hat.")
    credentials = transfer.get("credentials")
    if not isinstance(credentials, list) or not credentials:
        raise PlatformError("The transfer credential metadata is invalid.")
    names = [
        normalize_secret_name(str(item.get("name") or ""))
        for item in credentials
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    if len(names) != len(credentials):
        raise PlatformError("The transfer credential metadata is incomplete.")
    context = {
        "handoff_id": clean_handoff_id,
        "installation_id": str(transfer.get("installation_id") or "").strip(),
        "hat_handle": handle,
        "credential_names_sha256": credential_names_fingerprint_sha256(names),
        "consumer_public_key_fingerprint_sha256": str(
            transfer.get("consumer_public_key_fingerprint_sha256") or ""
        ).strip(),
    }
    envelope = create_authenticated_hat_secret_envelope(
        handle,
        consumer_public_key_pem=str(transfer.get("public_key_pem") or ""),
        expected_names=names,
        context=context,
        expected_creator_public_key_fingerprint_sha256=str(
            transfer.get("creator_public_key_fingerprint_sha256") or ""
        ),
    )
    submitted = client.post_json(
        f"{path}/credential-transfers/{clean_handoff_id}",
        {"ciphertext_payload": envelope},
    )
    if str(submitted.get("status") or "") != "submitted":
        raise PlatformError("The platform did not accept the encrypted Hat transfer.")
    return {
        "schema": RESULT_SCHEMA,
        "handoff_id": clean_handoff_id,
        "hat_handle": handle,
        "credential_count": len(names),
        "submitted": True,
        "authenticated_envelope": True,
        "value_available": False,
    }


__all__ = ["RESULT_SCHEMA", "complete_hat_credential_transfer"]
