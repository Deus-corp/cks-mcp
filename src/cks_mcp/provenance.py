"""
Provenance signing for VerificationRecord.

Ensures that only verify_source (the sole sanctioned constructor of
VerificationRecord objects) can produce a valid signature. Any
VerificationRecord without a signature that verifies against the
process-local secret is rejected by validate_knowledge.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

SIGNATURE_KEY = "_cks_mcp_signature"

_SECRET = os.urandom(32)

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