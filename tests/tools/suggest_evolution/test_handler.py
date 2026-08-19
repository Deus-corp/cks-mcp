"""Unit tests for the suggest_evolution MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)

pytestmark = pytest.mark.asyncio


def _real_runtime():
    from cks_runtime.adapters.cks_core import CksCoreAdapter
    from cks_runtime.runtime import Runtime
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



async def test_suggest_evolution_missing_parameters(mock_runtime):
    from cks_mcp.tools.suggest_evolution.handler import suggest_evolution
    result = await suggest_evolution(mock_runtime, {})
    assert result["error"] == "missing_parameter"


async def test_suggest_evolution_basic():
    from cks import parse

    from cks_mcp.tools.suggest_evolution.handler import suggest_evolution

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "obj-1", "type": "Concept", "name": "A"}, "structure": {}},'
        '{"identity": {"id": "obj-2", "type": "Concept", "name": "B"}, "structure": {}},'
        '{"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["obj-1", "obj-2"], "relation_type": "relates_to"}}'
        ']}'
    )
    session = await runtime.create_session(structure)

    result = await suggest_evolution(runtime, {
        "session_id": session.session_id,
        "description": "add a Concept about C and link it to A",
    })

    object_ids = {o["id"] for o in result["current_objects"]}
    assert object_ids == {"obj-1", "obj-2"}
    assert "rel-1" not in object_ids

    assert len(result["current_relations"]) == 1
    assert result["current_relations"][0]["id"] == "rel-1"
    assert result["current_relations"][0]["participants"] == ["obj-1", "obj-2"]
    assert "add_object" in " ".join(result["available_operation_types"])


async def test_suggest_evolution_preview_valid_operations():
    from cks import parse

    from cks_mcp.tools.suggest_evolution.handler import suggest_evolution

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "obj-1", "type": "Concept", "name": "A"}, "structure": {}}'
        ']}'
    )
    session = await runtime.create_session(structure)
    versions_before = len(runtime.get_session(session.session_id).versions) if hasattr(session, "versions") else None

    result = await suggest_evolution(runtime, {
        "session_id": session.session_id,
        "description": "add a Concept about B",
        "operations": [
            {
                "type": "add_object",
                "identity": {"id": "obj-2", "type": "Concept", "name": "B"},
                "structure": {},
            }
        ],
    })

    assert result["would_apply"] is True
    assert result["operations_previewed"] == 1
    assert result["diagnostics"] == []
    assert "preview_serialized" in result
    assert {o.identity.id for o in session.knowledge_structure.objects} == {"obj-1"}
    if versions_before is not None:
        assert len(runtime.get_session(session.session_id).versions) == versions_before


async def test_suggest_evolution_preview_invalid_operations_reports_diagnostics():
    from cks import parse

    from cks_mcp.tools.suggest_evolution.handler import suggest_evolution

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "obj-1", "type": "Concept", "name": "A"}, "structure": {}}'
        ']}'
    )
    session = await runtime.create_session(structure)

    result = await suggest_evolution(runtime, {
        "session_id": session.session_id,
        "description": "link A to something that doesn't exist",
        "operations": [
            {
                "type": "add_relation",
                "identity": {"id": "rel-1", "type": "Relation", "name": "r"},
                "participants": ["obj-1", "ghost"],
                "relation_type": "relates_to",
            }
        ],
    })

    assert result["would_apply"] is False
    assert "message" in result


async def test_suggest_evolution_preview_malformed_operations():
    from cks_mcp.tools.suggest_evolution.handler import suggest_evolution

    runtime = _real_runtime()
    from cks import parse
    structure = parse('{"objects": []}')
    session = await runtime.create_session(structure)

    result = await suggest_evolution(runtime, {
        "session_id": session.session_id,
        "description": "do something",
        "operations": [{"type": "not_a_real_operation"}],
    })

    assert result["error"] == "invalid_operations"
