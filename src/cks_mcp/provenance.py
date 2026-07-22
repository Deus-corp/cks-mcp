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


def verify_structure_provenance(structure: Any) -> list[dict[str, Any]]:
    """
    Check every VerificationRecord in *structure* for a valid signature.
    Returns a list of diagnostic dicts (empty if all records pass).
    """
    diagnostics: list[dict[str, Any]] = []
    record_to_subject: dict[str, str] = {}
    ambiguous_records: set[str] = set()

    # Build mapping from record_id -> subject_id
    for obj in structure.objects:
        if not hasattr(obj, 'identity') or obj.identity.type != "Relation":
            continue
        if obj.structure.get("relation_type") != "verified_by":
            continue
        participants = obj.structure.get("participants", [])
        if len(participants) != 2:
            continue
        subject_id, record_id = participants
        existing = record_to_subject.get(record_id)
        if existing is None:
            record_to_subject[record_id] = subject_id
        elif existing != subject_id:
            ambiguous_records.add(record_id)

    for obj in structure.objects:
        if not hasattr(obj, 'identity') or obj.identity.type != "VerificationRecord":
            continue
        record_id = obj.identity.id
        if record_id in ambiguous_records:
            diagnostics.append({
                "code": "CKS-MCP-AMBIGUOUS-VERIFICATION-REFERENCE",
                "severity": "error",
                "source": "mcp",
                "message": (
                    f"VerificationRecord '{record_id}' is referenced by multiple subjects "
                    f"through 'verified_by'. This relationship is ambiguous and must be resolved."
                ),
                "metadata": {"location": record_id},
            })
            continue

        subject_id = record_to_subject.get(record_id)
        if not subject_id:
            diagnostics.append({
                "code": "CKS-MCP-UNLINKED-VERIFICATION-RECORD",
                "severity": "warning",
                "source": "mcp",
                "message": (
                    f"VerificationRecord '{record_id}' has no verified_by relation. "
                    f"It will not be treated as a trusted provenance record."
                ),
                "metadata": {"location": record_id},
            })
            continue

        ok = verify(
            record_id=obj.identity.id,
            subject_id=subject_id,
            checked_at=obj.structure.get("checked_at", ""),
            checked_via=obj.structure.get("checked_via", ""),
            http_status=obj.structure.get("http_status"),
            signature=obj.structure.get(SIGNATURE_KEY),
        )
        if not ok:
            diagnostics.append({
                "code": "CKS-MCP-UNVERIFIED-PROVENANCE",
                "severity": "error",
                "source": "mcp",
                "message": (
                    f"VerificationRecord '{record_id}' does not carry a valid provenance signature. "
                    f"It must be produced by calling verify_source, not authored directly."
                ),
                "metadata": {"location": record_id},
            })

    return diagnostics