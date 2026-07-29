"""Integration tests for validate_knowledge's `extensions` parameter."""

from __future__ import annotations

import json

import pytest
from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.tools.validate import validate_knowledge

pytestmark = pytest.mark.asyncio


def make_runtime():
    return Runtime(core=CksCoreAdapter())


def _structure(represents_target: str) -> str:
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


async def test_extensions_absent_by_default():
    runtime = make_runtime()
    structure = {
        "objects": [
            {"identity": {"id": "src-1", "type": "Document", "name": "Real"}, "structure": {}},
            {"identity": {"id": "claim-1", "type": "EmbeddingProjection", "name": "c"}, "structure": {"store_ref": "vecdb://x"}},
            {"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["ghost-id", "claim-1"], "relation_type": "represents"}},
        ]
    }
    result = await validate_knowledge(runtime, {
        "json_data": json.dumps(structure),
        "extensions": ["embedding_projection"],
    })
    assert result["valid"] is False
    assert any(d["severity"] == "error" for d in result["diagnostics"])


async def test_extensions_catches_hallucinated_citation():
    runtime = make_runtime()
    structure = {
        "objects": [
            {"identity": {"id": "src-1", "type": "Document", "name": "Real"}, "structure": {}},
            {"identity": {"id": "claim-1", "type": "EmbeddingProjection", "name": "c"}, "structure": {"store_ref": "vecdb://x"}},
            {"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["ghost-id", "claim-1"], "relation_type": "represents"}},
        ]
    }
    result = await validate_knowledge(runtime, {
        "json_data": json.dumps(structure),
        "extensions": ["embedding_projection"],
    })
    assert result["valid"] is False
    assert any(d["severity"] == "error" for d in result["diagnostics"])


async def test_extensions_do_not_leak_into_global_registry():
    runtime = make_runtime()
    structure = {
        "objects": [
            {"identity": {"id": "src-1", "type": "Document", "name": "Real"}, "structure": {}},
            {"identity": {"id": "claim-1", "type": "EmbeddingProjection", "name": "c"}, "structure": {"store_ref": "vecdb://x"}},
            {"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["ghost-id", "claim-1"], "relation_type": "represents"}},
        ]
    }
    result = await validate_knowledge(runtime, {
        "json_data": json.dumps(structure),
        "extensions": ["embedding_projection"],
    })
    assert result["valid"] is False
    assert any(d["severity"] == "error" for d in result["diagnostics"])


async def test_extensions_passes_on_real_citation():
    runtime = make_runtime()
    result = await validate_knowledge(
        runtime,
        {"json_data": _structure("src-1"), "extensions": ["embedding_projection"]},
    )

    assert result["valid"] is True
    assert result["diagnostics"] == []


async def test_unknown_extension_returns_structured_error_not_crash():
    runtime = make_runtime()
    result = await validate_knowledge(
        runtime,
        {"json_data": _structure("src-1"), "extensions": ["not_a_real_extension"]},
    )

    assert result["error"] == "unknown_extension"
    assert "not_a_real_extension" in result["message"]
    assert "embedding_projection" in result["message"]