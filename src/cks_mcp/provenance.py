"""
Provenance signing for VerificationRecord.

Ensures that only verify_source (the sole sanctioned constructor of
VerificationRecord objects) can produce a valid signature. Any
VerificationRecord without a signature that verifies against the
configured secret is rejected by validate_knowledge.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any

SIGNATURE_KEY = "_cks_mcp_signature"


def _load_secret() -> bytes:
    """
    Load a stable secret from environment if provided.

    Supported formats:
    - raw UTF-8 string
    - hex string
    - base64 string prefixed with 'base64:'
    """
    raw = os.environ.get("CKS_MCP_SECRET")
    if not raw:
        # Fallback for development only. For production, set CKS_MCP_SECRET.
        return os.urandom(32)

    if raw.startswith("base64:"):
        return base64.b64decode(raw.removeprefix("base64:"))

    try:
        return bytes.fromhex(raw)
    except ValueError:
        return raw.encode("utf-8")


_SECRET = _load_secret()


def sign(
    record_id: str,
    subject_id: str,
    checked_at: str,
    checked_via: str,
    http_status: int | None,
) -> str:
    payload = f"{record_id}|{subject_id}|{checked_at}|{checked_via}|{http_status}"
    return hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()


def verify(
    record_id: str,
    subject_id: str,
    checked_at: str,
    checked_via: str,
    http_status: int | None,
    signature: str | None,
) -> bool:
    if not signature:
        return False
    expected = sign(record_id, subject_id, checked_at, checked_via, http_status)
    return hmac.compare_digest(expected, signature)