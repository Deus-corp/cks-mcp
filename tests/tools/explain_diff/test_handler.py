"""Unit tests for the explain_diff MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)

pytestmark = pytest.mark.asyncio


def _real_runtime():
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter
    return Runtime(core=CksCoreAdapter())



@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.core_bridge.validate.return_value = MagicMock(
        valid=True, diagnostics=[], metadata={}
    )
    runtime.core_bridge.serialize.return_value = '{"serialized":true}'
    runtime.core_bridge.explain.return_value = {
        "object_count": 1,
        "relation_count": 0,
        "summary": {"test": True},
    }
    # For evolve_knowledge, core_bridge.evolve must return an object with
    # .relations() (called by provenance).
    fake_evolved = MagicMock()
    fake_evolved.relations.return_value = []
    fake_evolved.objects = []
    runtime.core_bridge.evolve.return_value = fake_evolved

    session = MagicMock(session_id="s1", diagnostics=[])
    runtime.create_session = AsyncMock(return_value=session)

    tx = MagicMock(session=session)
    tx.results = [MagicMock(payload='{"serialized":true}')]
    runtime.begin_transaction.return_value = tx

    runtime.commit_transaction = AsyncMock(return_value=MagicMock(version_id="v1"))
    runtime.executor.execute = AsyncMock(return_value=MagicMock(
        succeeded=True,
        payload=fake_evolved,
        status=MagicMock(value="completed")
    ))

    return runtime



async def test_explain_diff_missing_parameters(mock_runtime):
    from cks_mcp.tools.explain_diff.handler import explain_diff
    result = await explain_diff(mock_runtime, {})
    assert result["error"] == "missing_parameter"


async def test_explain_diff_pure_add():
    from cks import parse

    from cks_mcp.tools.evolve.handler import evolve_knowledge
    from cks_mcp.tools.explain_diff.handler import explain_diff

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "obj-1", "type": "Concept", "name": "A"}, "structure": {}}'
        ']}'
    )
    session = await runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    await runtime.commit_transaction(tx)
    base_version = session.version_history[-1].version_id

    await evolve_knowledge(runtime, {
        "session_id": session.session_id,
        "operations": [
            {"type": "add_object", "identity": {"id": "obj-2", "type": "Concept", "name": "B"}, "structure": {}},
            {"type": "add_relation", "identity": {"id": "rel-1", "type": "Relation", "name": "r"},
             "participants": ["obj-1", "obj-2"], "relation_type": "relates_to"},
        ],
    })

    result = await explain_diff(runtime, {"session_id": session.session_id, "target_version_id": base_version})

    assert [o["id"] for o in result["details"]["added_objects"]] == ["obj-2"]
    assert result["details"]["removed_objects"] == []
    assert result["details"]["modified_objects"] == []
    assert [r["id"] for r in result["details"]["added_relations"]] == ["rel-1"]
    assert result["details"]["relinked_relations"] == []


async def test_explain_diff_modified_object_reported_as_modified_not_delete_add():
    from cks import parse

    from cks_mcp.tools.evolve.handler import evolve_knowledge
    from cks_mcp.tools.explain_diff.handler import explain_diff

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "obj-1", "type": "Concept", "name": "A"}, "structure": {"summary": "old"}},'
        '{"identity": {"id": "obj-2", "type": "Concept", "name": "B"}, "structure": {}},'
        '{"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["obj-1", "obj-2"], "relation_type": "relates_to"}}'
        ']}'
    )
    session = await runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    await runtime.commit_transaction(tx)
    base_version = session.version_history[-1].version_id

    await evolve_knowledge(runtime, {
        "session_id": session.session_id,
        "operations": [
            {"type": "update_object", "object_id": "obj-1", "structure_patch": {"summary": "new"}},
        ],
    })

    result = await explain_diff(runtime, {"session_id": session.session_id, "target_version_id": base_version})
    details = result["details"]

    assert details["added_objects"] == []
    assert details["removed_objects"] == []
    assert len(details["modified_objects"]) == 1
    assert details["modified_objects"][0]["id"] == "obj-1"
    assert details["modified_objects"][0]["changes"] == {"summary": {"from": "old", "to": "new"}}

    assert details["added_relations"] == []
    assert details["removed_relations"] == []
    assert details["modified_relations"] == []
    assert [r["id"] for r in details["relinked_relations"]] == ["rel-1"]

    assert "Modified 1 object" in result["summary"]
    assert "Re-linked 1 relation" in result["summary"]


async def test_explain_diff_recorded_inference_reported_as_reasoning():
    from cks import parse

    from cks_mcp.tools.evolve.handler import evolve_knowledge
    from cks_mcp.tools.explain_diff.handler import explain_diff

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "premise-1", "type": "Claim", "name": "P"}, "structure": {}},'
        '{"identity": {"id": "conclusion-1", "type": "Claim", "name": "C"}, "structure": {}}'
        ']}'
    )
    session = await runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    await runtime.commit_transaction(tx)
    base_version = session.version_history[-1].version_id

    await evolve_knowledge(runtime, {
        "session_id": session.session_id,
        "operations": [
            {"type": "record_inference",
             "identity": {"id": "step-1", "type": "InferenceStep", "name": "s1"},
             "structure": {
                 "premises": ["premise-1"], "conclusion": "conclusion-1",
                 "operator": "deductive", "confidence": 0.8,
             }},
        ],
    })

    result = await explain_diff(runtime, {"session_id": session.session_id, "target_version_id": base_version})
    steps = result["details"]["added_inference_steps"]

    assert len(steps) == 1
    assert steps[0]["id"] == "step-1"
    assert steps[0]["conclusion"] == "conclusion-1"
    assert list(steps[0]["premises"]) == ["premise-1"]
    assert steps[0]["operator"] == "deductive"
    assert steps[0]["confidence"] == 0.8
    assert "Recorded 1 inference" in result["summary"]
    assert "conclusion-1" in result["summary"]
    from cks import parse

    from cks_mcp.tools.evolve.handler import evolve_knowledge
    from cks_mcp.tools.explain_diff.handler import explain_diff

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "obj-1", "type": "Concept", "name": "A"}, "structure": {}},'
        '{"identity": {"id": "obj-2", "type": "Concept", "name": "B"}, "structure": {}},'
        '{"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["obj-1", "obj-2"], "relation_type": "derives_from"}}'
        ']}'
    )
    session = await runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    await runtime.commit_transaction(tx)
    base_version = session.version_history[-1].version_id

    await evolve_knowledge(runtime, {
        "session_id": session.session_id,
        "operations": [
            {"type": "remove_relation", "relation_id": "rel-1"},
            {"type": "add_relation", "identity": {"id": "rel-1", "type": "Relation", "name": "r"},
             "participants": ["obj-1", "obj-2"], "relation_type": "inspired_by"},
        ],
    })

    result = await explain_diff(runtime, {"session_id": session.session_id, "target_version_id": base_version})
    details = result["details"]

    assert details["relinked_relations"] == []
    assert details["added_relations"] == []
    assert details["removed_relations"] == []
    assert len(details["modified_relations"]) == 1
    assert details["modified_relations"][0]["changes"] == {
        "relation_type": {"from": "derives_from", "to": "inspired_by"}
    }
