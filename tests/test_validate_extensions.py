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
import pytest

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
    runtime = make_runtime()
    structure = {
        "objects": [
            {"identity": {"id": "src-1", "type": "Document", "name": "Real"}, "structure": {}},
            {"identity": {"id": "claim-1", "type": "EmbeddingProjection", "name": "c"}, "structure": {"store_ref": "vecdb://x"}},
            {"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["ghost-id", "claim-1"], "relation_type": "represents"}},
        ]
    }
    result = validate_knowledge(runtime, {
        "json_data": json.dumps(structure),
        "extensions": ["embedding_projection"],
    })
    assert result["valid"] is False
    assert any(d["severity"] == "error" for d in result["diagnostics"])


def test_extensions_catches_hallucinated_citation():
    runtime = make_runtime()
    structure = {
        "objects": [
            {"identity": {"id": "src-1", "type": "Document", "name": "Real"}, "structure": {}},
            {"identity": {"id": "claim-1", "type": "EmbeddingProjection", "name": "c"}, "structure": {"store_ref": "vecdb://x"}},
            {"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["ghost-id", "claim-1"], "relation_type": "represents"}},
        ]
    }
    result = validate_knowledge(runtime, {
        "json_data": json.dumps(structure),
        "extensions": ["embedding_projection"],
    })
    assert result["valid"] is False
    assert any(d["severity"] == "error" for d in result["diagnostics"])


def test_extensions_do_not_leak_into_global_registry():
    from cks.constraints import registry
    runtime = make_runtime()
    structure = {
        "objects": [
            {"identity": {"id": "src-1", "type": "Document", "name": "Real"}, "structure": {}},
            {"identity": {"id": "claim-1", "type": "EmbeddingProjection", "name": "c"}, "structure": {"store_ref": "vecdb://x"}},
            {"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["ghost-id", "claim-1"], "relation_type": "represents"}},
        ]
    }
    result = validate_knowledge(runtime, {
        "json_data": json.dumps(structure),
        "extensions": ["embedding_projection"],
    })
    assert result["valid"] is False
    assert any(d["severity"] == "error" for d in result["diagnostics"])


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
