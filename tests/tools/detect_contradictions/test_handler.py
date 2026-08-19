"""Unit tests for the detect_contradictions MCP tool."""

from __future__ import annotations

import pytest

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)

pytestmark = pytest.mark.asyncio


def _real_runtime():
    from cks_runtime.adapters.cks_core import CksCoreAdapter
    from cks_runtime.runtime import Runtime
    return Runtime(core=CksCoreAdapter())



async def test_detect_contradictions_no_session_no_conflicts():
    from cks_mcp.tools.detect_contradictions.handler import detect_contradictions

    runtime = _real_runtime()
    result = await detect_contradictions(runtime, {
        "json_data": '{"objects":[{"identity":{"id":"obj-1","type":"Concept","name":"A"},"structure":{}}]}'
    })
    assert result["contradiction_count"] == 0
    assert result["contradictions"] == []


async def test_detect_contradictions_with_session_no_conflicts():
    from cks import parse

    from cks_mcp.tools.detect_contradictions.handler import detect_contradictions

    runtime = _real_runtime()
    structure = parse(
        '{"objects":[{"identity":{"id":"obj-1","type":"Concept","name":"A"},"structure":{}}]}'
    )
    session = await runtime.create_session(structure)
    result = await detect_contradictions(runtime, {"session_id": session.session_id})
    assert result["contradiction_count"] == 0
    assert result["contradictions"] == []


async def test_detect_contradictions_mutual_exclusion():
    from cks import parse

    from cks_mcp.tools.detect_contradictions.handler import detect_contradictions

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "rule-1", "type": "MutualExclusionRule", "name": "r"}, '
        '"structure": {"relation_type_a": "supports", "relation_type_b": "contradicts"}},'
        '{"identity": {"id": "a", "type": "Claim", "name": "A"}, "structure": {}},'
        '{"identity": {"id": "b", "type": "Claim", "name": "B"}, "structure": {}},'
        '{"identity": {"id": "rel-1", "type": "Relation", "name": "r1"}, '
        '"structure": {"participants": ["a", "b"], "relation_type": "supports"}},'
        '{"identity": {"id": "rel-2", "type": "Relation", "name": "r2"}, '
        '"structure": {"participants": ["a", "b"], "relation_type": "contradicts"}}'
        ']}'
    )
    session = await runtime.create_session(structure)
    result = await detect_contradictions(runtime, {"session_id": session.session_id})
    assert result["contradiction_count"] == 1
    assert len(result["contradictions"]) == 1
    assert result["contradictions"][0]["code"] == "CKS-EXT-MUTUAL-EXCLUSION"


async def test_detect_contradictions_functional_relation():
    from cks import parse

    from cks_mcp.tools.detect_contradictions.handler import detect_contradictions

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "rule-1", "type": "FunctionalRelationRule", "name": "r"}, '
        '"structure": {"relation_type": "orbits"}},'
        '{"identity": {"id": "earth", "type": "Planet", "name": "Earth"}, "structure": {}},'
        '{"identity": {"id": "sun", "type": "Star", "name": "Sun"}, "structure": {}},'
        '{"identity": {"id": "mars", "type": "Planet", "name": "Mars"}, "structure": {}},'
        '{"identity": {"id": "rel-1", "type": "Relation", "name": "r1"}, '
        '"structure": {"participants": ["earth", "sun"], "relation_type": "orbits"}},'
        '{"identity": {"id": "rel-2", "type": "Relation", "name": "r2"}, '
        '"structure": {"participants": ["earth", "mars"], "relation_type": "orbits"}}'
        ']}'
    )
    session = await runtime.create_session(structure)
    result = await detect_contradictions(runtime, {"session_id": session.session_id})
    assert result["contradiction_count"] == 1
    assert len(result["contradictions"]) == 1
    assert result["contradictions"][0]["code"] == "CKS-EXT-FUNCTIONAL-RELATION"


async def test_detect_contradictions_inference_confidence_conflict():
    from cks import parse

    from cks_mcp.tools.detect_contradictions.handler import detect_contradictions

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "premise-1", "type": "Claim", "name": "P"}, "structure": {}},'
        '{"identity": {"id": "conclusion-1", "type": "Claim", "name": "C"}, "structure": {}},'
        '{"identity": {"id": "step-1", "type": "InferenceStep", "name": "s1"}, '
        '"structure": {"premises": ["premise-1"], "conclusion": "conclusion-1", "confidence": 0.9}},'
        '{"identity": {"id": "step-2", "type": "InferenceStep", "name": "s2"}, '
        '"structure": {"premises": ["premise-1"], "conclusion": "conclusion-1", "confidence": 0.2}}'
        ']}'
    )
    session = await runtime.create_session(structure)
    result = await detect_contradictions(runtime, {"session_id": session.session_id})
    assert result["contradiction_count"] == 1
    assert result["contradictions"][0]["code"] == "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT"
    assert result["contradictions"][0]["severity"] == "warning"


async def test_detect_contradictions_ignores_superseded_inference_step():
    from cks import parse

    from cks_mcp.tools.detect_contradictions.handler import detect_contradictions

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "conclusion-1", "type": "Claim", "name": "C"}, "structure": {}},'
        '{"identity": {"id": "step-1", "type": "InferenceStep", "name": "s1"}, '
        '"structure": {"conclusion": "conclusion-1", "confidence": 0.2, "superseded_by": "step-2"}},'
        '{"identity": {"id": "step-2", "type": "InferenceStep", "name": "s2"}, '
        '"structure": {"conclusion": "conclusion-1", "confidence": 0.9}}'
        ']}'
    )
    session = await runtime.create_session(structure)
    result = await detect_contradictions(runtime, {"session_id": session.session_id})
    assert result["contradiction_count"] == 0


async def test_detect_contradictions_missing_json_data():
    from cks_mcp.tools.detect_contradictions.handler import detect_contradictions

    runtime = _real_runtime()
    result = await detect_contradictions(runtime, {})
    assert "error" in result
    assert result["error"] == "missing_parameter"
