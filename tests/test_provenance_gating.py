"""
Regression tests for provenance gating on every json_data entry point
that can call runtime.create_session.

Before the 1.3.3 fix, validate_knowledge always committed a version
first and only checked VerificationRecord signatures afterward --
purely to set the response's 'valid' field, never to block the commit
itself. A forged VerificationRecord therefore still ended up as a
real, persisted version (and from there, visible via
serialize_knowledge, explain_knowledge, query_subgraph, or the MCP
Resources surface with no indication it was ever flagged invalid).
evolve_knowledge and merge_knowledge/merge_branch already gated their
commits on this same check (see CHANGELOG 1.2.6).

serialize_knowledge and explain_knowledge were never updated to
match: their json_data fallback path (used when no session_id is
given) called runtime.create_session unconditionally, so a caller
could skip validate_knowledge entirely and commit a forged
VerificationRecord as a real, readable session just by calling
serialize_knowledge or explain_knowledge directly. The
TestSerializeExplainProvenanceGating tests below lock in the fix for
that bypass; the tests above them cover validate_knowledge as before.

Real Runtime + CksCoreAdapter (not MagicMock), matching
test_validate_extensions.py, because what's under test is genuine
commit/no-commit behavior through Runtime's transaction pipeline.
"""

from __future__ import annotations

import json

import pytest
from cks_runtime.adapters.cks_core import CksCoreAdapter
from cks_runtime.runtime import Runtime

from cks_mcp import provenance
from cks_mcp.tools.explain.handler import explain_knowledge
from cks_mcp.tools.serialize.handler import serialize_knowledge
from cks_mcp.tools.validate.handler import validate_knowledge

pytestmark = pytest.mark.asyncio


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


async def test_forged_verification_record_is_not_committed():
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
    result = await validate_knowledge(runtime, {"json_data": _structure_with_record("totally-fake-signature")})

    assert result["valid"] is False
    assert "version_id" not in result
    assert "session_id" not in result
    assert any(d["code"] == "CKS-MCP-UNVERIFIED-PROVENANCE" for d in result["diagnostics"])
    assert runtime.sessions.list_sessions() == ()


def _structure_with_record_and_relation_type(signature: str | None, relation_identity_type: str) -> str:
    """Same as _structure_with_record, but with the linking relation's
    identity.type overridable -- to test that relation detection is
    structural (participants + relation_type), not keyed off this
    caller-chosen label."""
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
                "identity": {"id": "rel-1", "type": relation_identity_type, "name": "r"},
                "structure": {"participants": ["claim-1", "vr-1"], "relation_type": "verified_by"},
            },
        ]
    })


async def test_forged_verification_record_is_not_committed_regardless_of_relation_identity_type():
    """
    Regression test for a critical provenance bypass: relation
    detection in verify_structure_provenance used to key off the
    linking relation's identity.type string (checking for the literal
    "Relation"), but cks-core itself classifies relations structurally
    -- from 'participants' + 'relation_type' in `structure`, never from
    identity.type (see CanonicalDeserializer._parse_object in
    cks-core). A relation labeled with any other identity.type (e.g.
    "VerifiedByLink") was therefore invisible to the record_to_subject
    mapping, routing even a fully forged, unsigned VerificationRecord
    into the WARNING-only "unlinked" branch instead of the ERROR branch
    that calls verify() -- letting it commit as a real, valid version.
    """
    runtime = make_runtime()
    result = await validate_knowledge(runtime, {
        "json_data": _structure_with_record_and_relation_type("totally-fake-signature", "VerifiedByLink")
    })

    assert result["valid"] is False
    assert "version_id" not in result
    assert "session_id" not in result
    assert any(d["code"] == "CKS-MCP-UNVERIFIED-PROVENANCE" for d in result["diagnostics"])
    assert runtime.sessions.list_sessions() == ()


async def test_genuinely_signed_record_is_recognized_regardless_of_relation_identity_type():
    """The fix must not overcorrect into rejecting everything whose
    linking relation isn't labeled "Relation" -- a genuinely signed
    record must still validate and commit no matter what identity.type
    its 'verified_by' relation carries."""
    runtime = make_runtime()
    signature = provenance.sign("vr-1", "claim-1", "2026-01-01T00:00:00Z", "automated_http_check", 200)

    result = await validate_knowledge(runtime, {
        "json_data": _structure_with_record_and_relation_type(signature, "VerifiedByLink")
    })

    assert result["valid"] is True
    assert result["diagnostics"] == []
    assert "version_id" in result


async def test_missing_signature_is_not_committed():
    runtime = make_runtime()
    result = await validate_knowledge(runtime, {"json_data": _structure_with_record(None)})

    assert result["valid"] is False
    assert "version_id" not in result
    assert "session_id" not in result
    assert runtime.sessions.list_sessions() == ()


async def test_genuinely_signed_verification_record_is_committed():
    runtime = make_runtime()
    signature = provenance.sign("vr-1", "claim-1", "2026-01-01T00:00:00Z", "automated_http_check", 200)

    result = await validate_knowledge(runtime, {"json_data": _structure_with_record(signature)})

    assert result["valid"] is True
    assert "version_id" in result
    assert result["diagnostics"] == []

    session = runtime.get_session(result["session_id"])
    assert session.version_count == 1


async def test_revalidating_an_existing_session_does_not_commit_on_forged_record():
    """Same gate applies on the session_id path, not just fresh
    json_data -- re-validating a session that already carries a
    forged record must not add a new committed version either."""
    runtime = make_runtime()
    import cks
    structure = cks.parse(_structure_with_record("totally-fake-signature"))
    session = await runtime.create_session(structure)
    assert session.version_count == 0

    result = await validate_knowledge(runtime, {"session_id": session.session_id})

    assert result["valid"] is False
    assert "version_id" not in result
    assert session.version_count == 0


async def test_evolve_does_not_block_on_unlinked_warning_only():
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
    from cks_mcp.tools.evolve.handler import evolve_knowledge

    runtime = make_runtime()
    base = await validate_knowledge(runtime, {
        "json_data": json.dumps({
            "objects": [{"identity": {"id": "claim-1", "type": "Definition", "name": "Claim"}, "structure": {}}],
        })
    })
    assert base["valid"] is True
    session_id = base["session_id"]

    signature = provenance.sign("vr-1", "claim-1", "2026-01-01T00:00:00Z", "automated_http_check", 200)
    result = await evolve_knowledge(runtime, {
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


async def test_structure_without_any_verification_record_is_unaffected():
    """No VerificationRecord at all -> provenance check is trivially
    satisfied and behavior is exactly as before this fix."""
    runtime = make_runtime()
    json_data = json.dumps({
        "objects": [
            {"identity": {"id": "obj-1", "type": "Definition", "name": "Test"}, "structure": {}},
        ]
    })

    result = await validate_knowledge(runtime, {"json_data": json_data})

    assert result["valid"] is True
    assert "version_id" in result
    session = runtime.get_session(result["session_id"])
    assert session.version_count == 1


class TestSerializeExplainProvenanceGating:
    """
    serialize_knowledge and explain_knowledge's json_data fallback path
    (no session_id given) must not bypass the same provenance gate
    validate_knowledge/evolve_knowledge/merge_knowledge enforce -- see
    module docstring.
    """

    async def test_serialize_knowledge_rejects_forged_record(self):
        runtime = make_runtime()
        result = await serialize_knowledge(
            runtime, {"json_data": _structure_with_record("totally-fake-signature")}
        )

        assert isinstance(result, dict)
        assert result["error"] == "unverified_provenance"
        assert any(
            d["code"] == "CKS-MCP-UNVERIFIED-PROVENANCE" for d in result["details"]
        )
        assert runtime.sessions.list_sessions() == ()

    async def test_serialize_knowledge_rejects_missing_signature(self):
        runtime = make_runtime()
        result = await serialize_knowledge(
            runtime, {"json_data": _structure_with_record(None)}
        )

        assert isinstance(result, dict)
        assert result["error"] == "unverified_provenance"
        assert runtime.sessions.list_sessions() == ()

    async def test_serialize_knowledge_still_commits_genuine_record(self):
        runtime = make_runtime()
        signature = provenance.sign(
            "vr-1", "claim-1", "2026-01-01T00:00:00Z", "automated_http_check", 200
        )

        result = await serialize_knowledge(
            runtime, {"json_data": _structure_with_record(signature)}
        )

        assert not (isinstance(result, dict) and result.get("error"))
        assert len(runtime.sessions.list_sessions()) == 1
        assert runtime.sessions.list_sessions()[0].version_count == 1

    async def test_explain_knowledge_rejects_forged_record(self):
        runtime = make_runtime()
        result = await explain_knowledge(
            runtime, {"json_data": _structure_with_record("totally-fake-signature")}
        )

        assert result["error"] == "unverified_provenance"
        assert any(
            d["code"] == "CKS-MCP-UNVERIFIED-PROVENANCE" for d in result["details"]
        )
        assert runtime.sessions.list_sessions() == ()

    async def test_explain_knowledge_rejects_missing_signature(self):
        runtime = make_runtime()
        result = await explain_knowledge(
            runtime, {"json_data": _structure_with_record(None)}
        )

        assert result["error"] == "unverified_provenance"
        assert runtime.sessions.list_sessions() == ()

    async def test_explain_knowledge_still_commits_genuine_record(self):
        runtime = make_runtime()
        signature = provenance.sign(
            "vr-1", "claim-1", "2026-01-01T00:00:00Z", "automated_http_check", 200
        )

        result = await explain_knowledge(
            runtime, {"json_data": _structure_with_record(signature)}
        )

        assert "error" not in result
        assert len(runtime.sessions.list_sessions()) == 1
        assert runtime.sessions.list_sessions()[0].version_count == 1

    async def test_explain_knowledge_unaffected_without_verification_record(self):
        runtime = make_runtime()
        json_data = json.dumps({
            "objects": [
                {"identity": {"id": "obj-1", "type": "Definition", "name": "Test"}, "structure": {}},
            ]
        })

        result = await explain_knowledge(runtime, {"json_data": json_data})

        assert "error" not in result
        assert len(runtime.sessions.list_sessions()) == 1