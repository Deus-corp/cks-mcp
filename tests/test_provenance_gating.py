"""
Regression tests for validate_knowledge's provenance gating.

Before this fix, validate_knowledge always committed a version first
and only checked VerificationRecord signatures afterward -- purely to
set the response's 'valid' field, never to block the commit itself.
A forged VerificationRecord therefore still ended up as a real,
persisted version (and from there, visible via serialize_knowledge,
explain_knowledge, query_subgraph, or the MCP Resources surface with
no indication it was ever flagged invalid). evolve_knowledge and
merge_knowledge/merge_branch already gated their commits on this same
check (see CHANGELOG 1.2.6) -- these tests lock in that
validate_knowledge now does too.

Real Runtime + CksCoreAdapter (not MagicMock), matching
test_validate_extensions.py, because what's under test is genuine
commit/no-commit behavior through Runtime's transaction pipeline.
"""

from __future__ import annotations

import json

from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp import provenance
from cks_mcp.tools.validate import validate_knowledge


def make_runtime() -> Runtime:
    return Runtime(core=CksCoreAdapter())


def _structure_with_record(signature: str | None) -> str:
    """A Definition plus a VerificationRecord 'verified_by' it, with
    the given (possibly forged) signature. Structurally well-formed
    either way -- checked_via/http_status/checked_at all satisfy
    cks-core's own VerificationRecordIntegrityConstraint regardless of
    whether the signature itself is genuine, isolating the test to the
    MCP-level provenance check specifically."""
    record_structure = {
        "checked_at": "2026-01-01T00:00:00Z",
        "checked_via": "automated_http_check",
        "http_status": 200,
    }
    if signature is not None:
        record_structure[provenance.SIGNATURE_KEY] = signature

    return json.dumps({
        "objects": [
            {
                "identity": {"id": "claim-1", "type": "Definition", "name": "Claim"},
                "structure": {"text": "the sky is blue"},
            },
            {
                "identity": {"id": "vr-1", "type": "VerificationRecord", "name": "check"},
                "structure": record_structure,
            },
            {
                "identity": {"id": "rel-1", "type": "Relation", "name": "r"},
                "structure": {"participants": ["claim-1", "vr-1"], "relation_type": "verified_by"},
            },
        ]
    })


def test_forged_verification_record_is_not_committed():
    """
    Note: an earlier version of this fix (1.3.3) still called
    create_session() before the provenance check, reasoning that
    "the session itself is real, just never committed -- what
    matters is that no version was persisted." Live testing against
    a running server showed that reasoning doesn't hold:
    runtime.create_session() persists immediately (storage.save_session),
    and the resulting session_id was still fully readable via
    serialize_knowledge/explain_knowledge/query_subgraph/MCP Resources,
    exposing the exact forged content this gate exists to hide -- just
    one layer up from the version-level leak this test file was
    originally written to close. Nothing should be created or
    retrievable for content that gets rejected.
    """
    runtime = make_runtime()
    result = validate_knowledge(runtime, {"json_data": _structure_with_record("totally-fake-signature")})

    assert result["valid"] is False
    assert "version_id" not in result
    assert "session_id" not in result
    assert any(d["code"] == "CKS-MCP-UNVERIFIED-PROVENANCE" for d in result["diagnostics"])
    assert runtime.sessions.list_sessions() == ()


def test_missing_signature_is_not_committed():
    runtime = make_runtime()
    result = validate_knowledge(runtime, {"json_data": _structure_with_record(None)})

    assert result["valid"] is False
    assert "version_id" not in result
    assert "session_id" not in result
    assert runtime.sessions.list_sessions() == ()


def test_genuinely_signed_verification_record_is_committed():
    runtime = make_runtime()
    signature = provenance.sign("vr-1", "claim-1", "2026-01-01T00:00:00Z", "automated_http_check", 200)

    result = validate_knowledge(runtime, {"json_data": _structure_with_record(signature)})

    assert result["valid"] is True
    assert "version_id" in result
    assert result["diagnostics"] == []

    session = runtime.get_session(result["session_id"])
    assert session.version_count == 1


def test_revalidating_an_existing_session_does_not_commit_on_forged_record():
    """Same gate applies on the session_id path, not just fresh
    json_data -- re-validating a session that already carries a
    forged record must not add a new committed version either."""
    runtime = make_runtime()
    import cks
    structure = cks.parse(_structure_with_record("totally-fake-signature"))
    session = runtime.create_session(structure)
    assert session.version_count == 0

    result = validate_knowledge(runtime, {"session_id": session.session_id})

    assert result["valid"] is False
    assert "version_id" not in result
    assert session.version_count == 0


def test_evolve_does_not_block_on_unlinked_warning_only():
    """
    A genuinely-signed VerificationRecord with no verified_by relation
    yet (e.g. added in one evolve_knowledge call, to be linked in a
    later one) triggers only the 'warning'-severity
    CKS-MCP-UNLINKED-VERIFICATION-RECORD diagnostic -- not an error.
    evolve_knowledge must not block on this; only 'error'-severity
    provenance diagnostics (forged/ambiguous) should. Confirmed live
    against a running server that this previously hard-rejected a real
    verify_source-produced record with a misleading "invalid or
    missing provenance signature" message.
    """
    from cks_mcp.tools.evolve import evolve_knowledge
    from cks_mcp.tools.validate import validate_knowledge

    runtime = make_runtime()
    base = validate_knowledge(runtime, {
        "json_data": json.dumps({
            "objects": [{"identity": {"id": "claim-1", "type": "Definition", "name": "Claim"}, "structure": {}}],
        })
    })
    assert base["valid"] is True
    session_id = base["session_id"]

    signature = provenance.sign("vr-1", "claim-1", "2026-01-01T00:00:00Z", "automated_http_check", 200)
    result = evolve_knowledge(runtime, {
        "session_id": session_id,
        "operations": [{
            "type": "add_object",
            "identity": {"id": "vr-1", "type": "VerificationRecord", "name": "check"},
            "structure": {
                "checked_at": "2026-01-01T00:00:00Z",
                "checked_via": "automated_http_check",
                "http_status": 200,
                provenance.SIGNATURE_KEY: signature,
            },
        }],
    })

    assert result.get("evolved") is True, result
    assert "version_id" in result


def test_structure_without_any_verification_record_is_unaffected():
    """No VerificationRecord at all -> provenance check is trivially
    satisfied and behavior is exactly as before this fix."""
    runtime = make_runtime()
    json_data = json.dumps({
        "objects": [
            {"identity": {"id": "obj-1", "type": "Definition", "name": "Test"}, "structure": {}},
        ]
    })

    result = validate_knowledge(runtime, {"json_data": json_data})

    assert result["valid"] is True
    assert "version_id" in result
    session = runtime.get_session(result["session_id"])
    assert session.version_count == 1