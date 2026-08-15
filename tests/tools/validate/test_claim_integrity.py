"""Integration tests for validate_knowledge's `claim_integrity` extension."""

from __future__ import annotations

import json

import pytest
from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.tools.validate.handler import validate_knowledge

pytestmark = pytest.mark.asyncio


def make_runtime():
    return Runtime(core=CksCoreAdapter())


def _claim_structure(**overrides) -> dict:
    data = {
        "statement": "The Earth orbits the Sun.",
        "confidence": 0.97,
        "author": "researcher-agent",
        "created_at": "2026-08-15T00:00:00Z",
        "status": "accepted",
    }
    data.update(overrides)
    return {
        "objects": [
            {
                "identity": {"id": "claim-1", "type": "Claim", "name": "Earth orbits Sun"},
                "structure": data,
            }
        ]
    }


async def test_validate_knowledge_accepts_valid_claim_with_extension():
    runtime = make_runtime()
    result = await validate_knowledge(runtime, {
        "json_data": json.dumps(_claim_structure()),
        "extensions": ["claim_integrity"],
    })
    assert result["valid"] is True


async def test_validate_knowledge_rejects_malformed_claim_with_extension():
    runtime = make_runtime()
    result = await validate_knowledge(runtime, {
        "json_data": json.dumps(_claim_structure(confidence=1.5, statement="")),
        "extensions": ["claim_integrity"],
    })
    assert result["valid"] is False
    assert any(d["code"] == "CKS-EXT-CLAIM-INTEGRITY" for d in result["diagnostics"])


async def test_validate_knowledge_ignores_malformed_claim_without_extension():
    runtime = make_runtime()
    result = await validate_knowledge(runtime, {
        "json_data": json.dumps(_claim_structure(confidence=1.5, statement="")),
    })
    assert result["valid"] is True
