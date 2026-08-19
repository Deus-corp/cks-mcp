"""Integration test: evolve_knowledge validates a Claim added through
evolution when the 'claim_integrity' extension is requested."""

from __future__ import annotations

import json

import pytest

from cks_mcp.tools.evolve.handler import evolve_knowledge

pytestmark = pytest.mark.asyncio

_EMPTY_STRUCTURE_JSON = '{"objects": []}'

_VALID_CLAIM_IDENTITY = {"id": "claim-1", "type": "Claim", "name": "Earth orbits Sun"}
_VALID_CLAIM_STRUCTURE = {
    "statement": "The Earth orbits the Sun.",
    "confidence": 0.97,
    "author": "researcher-agent",
    "created_at": "2026-08-15T00:00:00Z",
    "status": "accepted",
}
_MALFORMED_CLAIM_STRUCTURE = {
    "statement": "",
    "confidence": 1.5,
    "author": "researcher-agent",
    "created_at": "2026-08-15T00:00:00Z",
    "status": "accepted",
}


def _real_runtime():
    from cks_runtime.adapters.cks_core import CksCoreAdapter
    from cks_runtime.runtime import Runtime
    return Runtime(core=CksCoreAdapter())


async def test_evolve_knowledge_accepts_valid_claim_with_extension():
    runtime = _real_runtime()
    result = await evolve_knowledge(
        runtime,
        {
            "json_data": _EMPTY_STRUCTURE_JSON,
            "operations": [
                {
                    "type": "add_object",
                    "identity": _VALID_CLAIM_IDENTITY,
                    "structure": _VALID_CLAIM_STRUCTURE,
                }
            ],
            "extensions": ["claim_integrity"],
        },
    )
    assert result.get("evolved") is True
    objs = {o["identity"]["id"]: o for o in json.loads(result["serialized"])["objects"]}
    assert objs["claim-1"]["structure"]["statement"] == "The Earth orbits the Sun."


async def test_evolve_knowledge_rejects_malformed_claim_with_extension():
    runtime = _real_runtime()
    result = await evolve_knowledge(
        runtime,
        {
            "json_data": _EMPTY_STRUCTURE_JSON,
            "operations": [
                {
                    "type": "add_object",
                    "identity": _VALID_CLAIM_IDENTITY,
                    "structure": _MALFORMED_CLAIM_STRUCTURE,
                }
            ],
            "extensions": ["claim_integrity"],
        },
    )
    assert result["error"] == "validation_failed"
    assert any(d["code"] == "CKS-EXT-CLAIM-INTEGRITY" for d in result["diagnostics"])


async def test_evolve_knowledge_without_extension_does_not_check_claim_integrity():
    runtime = _real_runtime()
    result = await evolve_knowledge(
        runtime,
        {
            "json_data": _EMPTY_STRUCTURE_JSON,
            "operations": [
                {
                    "type": "add_object",
                    "identity": _VALID_CLAIM_IDENTITY,
                    "structure": _MALFORMED_CLAIM_STRUCTURE,
                }
            ],
        },
    )
    # Built-in constraints alone never look at Claim's fields, so this
    # commits despite the malformed Claim -- the exact gap 'extensions'
    # lets a caller close for this call.
    assert result.get("evolved") is True
    assert "extensions_applied" not in result
