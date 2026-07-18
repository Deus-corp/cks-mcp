"""
Integration tests for validate_knowledge's `extensions` parameter.

Unlike test_tools.py, these use a *real* Runtime + CksCoreAdapter
(not MagicMock) because the thing under test is genuine cks-core
validation behaviour -- specifically, that a caller can opt the
EmbeddingProjectionIntegrityConstraint extension in for a single
MCP tool call, end-to-end through Runtime's session/transaction
pipeline, exactly the anti-hallucination-citation scenario this
parameter was built for.
"""

from __future__ import annotations

import json

from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.tools.validate import validate_knowledge


def make_runtime() -> Runtime:
    return Runtime(core=CksCoreAdapter())


def _structure(represents_target: str) -> str:
    """A Document plus an EmbeddingProjection 'represents' relation
    pointing at `represents_target` (a real id, or a fabricated one)."""
    return json.dumps({
        "objects": [
            {
                "identity": {"id": "src-1", "type": "Document", "name": "Real paper"},
                "structure": {"content": "actual text"},
            },
            {
                "identity": {"id": "claim-1", "type": "EmbeddingProjection", "name": "claim"},
                "structure": {"store_ref": "vecdb://xyz"},
            },
            {
                "identity": {"id": "rel-1", "type": "Relation", "name": "r"},
                "structure": {
                    "participants": [represents_target, "claim-1"],
                    "relation_type": "represents",
                },
            },
        ]
    })


def test_extensions_absent_by_default():
    """Without `extensions`, behaviour is unchanged from before this
    feature existed: the dangling reference is still caught by the
    core NoDanglingRelationConstraint, but not by the extension."""
    runtime = make_runtime()
    result = validate_knowledge(runtime, {"json_data": _structure("ghost-id")})

    assert result["valid"] is False
    assert result["extensions_applied"] == []
    codes = {d["code"] for d in result["diagnostics"]}
    assert "CKS-STRUCT-DANGLING-REF" in codes
    assert "CKS-EXT-EMBEDDING-PROJECTION" not in codes


def test_extensions_catches_hallucinated_citation():
    """The scenario this parameter exists for: an EmbeddingProjection
    'representing' a source id that does not exist in the structure
    -- a mechanically detectable citation hallucination."""
    runtime = make_runtime()
    result = validate_knowledge(
        runtime,
        {"json_data": _structure("ghost-id"), "extensions": ["embedding_projection"]},
    )

    assert result["valid"] is False
    assert result["extensions_applied"] == ["embedding_projection"]
    codes = {d["code"] for d in result["diagnostics"]}
    assert "CKS-EXT-EMBEDDING-PROJECTION" in codes
    assert any("claim-1" in d["message"] for d in result["diagnostics"])


def test_extensions_passes_on_real_citation():
    """A genuine, existing source id must pass cleanly with the
    extension enabled."""
    runtime = make_runtime()
    result = validate_knowledge(
        runtime,
        {"json_data": _structure("src-1"), "extensions": ["embedding_projection"]},
    )

    assert result["valid"] is True
    assert result["diagnostics"] == []


def test_unknown_extension_returns_structured_error_not_crash():
    runtime = make_runtime()
    result = validate_knowledge(
        runtime,
        {"json_data": _structure("src-1"), "extensions": ["not_a_real_extension"]},
    )

    assert result["error"] == "unknown_extension"
    assert "not_a_real_extension" in result["message"]
    assert "embedding_projection" in result["message"]


def test_extensions_do_not_leak_into_global_registry():
    """A per-call extension must never become visible to a later
    call that didn't ask for it (the exact global-mutation problem
    this whole feature was built to avoid)."""
    from cks.constraints import registry

    runtime = make_runtime()
    validate_knowledge(
        runtime,
        {"json_data": _structure("ghost-id"), "extensions": ["embedding_projection"]},
    )

    assert "CKS-EXT-EMBEDDING-PROJECTION" not in registry.names()

    # A subsequent call with no extensions must not see it either.
    result = validate_knowledge(runtime, {"json_data": _structure("ghost-id")})
    codes = {d["code"] for d in result["diagnostics"]}
    assert "CKS-EXT-EMBEDDING-PROJECTION" not in codes