"""Unit tests for the visualize_graph MCP tool."""

from __future__ import annotations

import json
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



async def test_visualize_graph_missing_session_id(mock_runtime):
    from cks_mcp.tools.visualize_graph.handler import visualize_graph
    result = await visualize_graph(mock_runtime, {})
    assert result["error"] == "missing_parameter"
    assert "session_id" in result["message"]


async def test_visualize_graph_basic():
    from cks import parse

    from cks_mcp.tools.visualize_graph.handler import visualize_graph

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "obj-1", "type": "Concept", "name": "Natural Selection"}, "structure": {}},'
        '{"identity": {"id": "obj-2", "type": "Document", "name": "Origin of Species"}, "structure": {}},'
        '{"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["obj-1", "obj-2"], "relation_type": "derives_from"}}'
        ']}'
    )
    session = await runtime.create_session(structure)
    result = await visualize_graph(runtime, {"session_id": session.session_id})

    assert "mermaid" in result
    mermaid = result["mermaid"]
    assert "n0[" in mermaid
    assert "n1[" in mermaid
    assert "n2[" not in mermaid
    assert "obj-1[" not in mermaid
    assert "obj-2[" not in mermaid


async def test_visualize_graph_invalid_mode():
    from cks import parse

    from cks_mcp.tools.visualize_graph.handler import visualize_graph

    runtime = _real_runtime()
    structure = parse(VALID_KNOWLEDGE_JSON)
    session = await runtime.create_session(structure)

    result = await visualize_graph(
        runtime, {"session_id": session.session_id, "mode": "bogus"}
    )
    assert result["error"] == "invalid_parameter"
    assert "mode" in result["message"]


async def test_visualize_graph_inference_mode_basic_chain():
    from cks import parse

    from cks_mcp.tools.evolve.handler import evolve_knowledge
    from cks_mcp.tools.visualize_graph.handler import visualize_graph

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "fact-1", "type": "Claim", "name": "P1"}, "structure": {}},'
        '{"identity": {"id": "fact-2", "type": "Claim", "name": "P2"}, "structure": {}},'
        '{"identity": {"id": "concl-1", "type": "Claim", "name": "C"}, "structure": {}}'
        ']}'
    )
    session = await runtime.create_session(structure)
    await evolve_knowledge(runtime, {
        "session_id": session.session_id,
        "operations": [
            {"type": "record_inference",
             "identity": {"id": "step-1", "type": "InferenceStep", "name": "s1"},
             "structure": {
                 "premises": ["fact-1", "fact-2"], "conclusion": "concl-1",
                 "operator": "deductive", "confidence": 0.9,
             }},
        ],
    })

    # No seed_ids: auto-discovers concl-1 as the target since it's the
    # conclusion of an active InferenceStep.
    result = await visualize_graph(
        runtime, {"session_id": session.session_id, "mode": "inference"}
    )
    mermaid = result["mermaid"]
    assert '"P1 (Claim)"' in mermaid
    assert '"P2 (Claim)"' in mermaid
    assert '"C (Claim)"' in mermaid
    assert '"deductive, confidence 0.9"' in mermaid
    assert '-->|"concludes"|' in mermaid
    assert '-->|"premise"|' in mermaid
    assert result["returned_nodes"] == 4  # 3 objects + 1 step
    assert result["is_truncated"] is False


async def test_visualize_graph_inference_mode_cites_step_and_superseded():
    from cks import parse

    from cks_mcp.tools.evolve.handler import evolve_knowledge
    from cks_mcp.tools.visualize_graph.handler import visualize_graph

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "fact-1", "type": "Claim", "name": "Old evidence"}, "structure": {}},'
        '{"identity": {"id": "fact-2", "type": "Claim", "name": "New evidence"}, "structure": {}},'
        '{"identity": {"id": "concl-1", "type": "Claim", "name": "Estimate"}, "structure": {}}'
        ']}'
    )
    session = await runtime.create_session(structure)
    await evolve_knowledge(runtime, {
        "session_id": session.session_id,
        "operations": [
            {"type": "record_inference",
             "identity": {"id": "step-old", "type": "InferenceStep", "name": "old"},
             "structure": {
                 "premises": ["fact-1"], "conclusion": "concl-1",
                 "operator": "estimate", "confidence": 0.5,
                 "superseded_by": "step-new",
             }},
            {"type": "record_inference",
             "identity": {"id": "step-new", "type": "InferenceStep", "name": "new"},
             "structure": {
                 # cites step-old directly (meta-reasoning citation), not
                 # just its conclusion.
                 "premises": ["fact-2", "step-old"], "conclusion": "concl-1",
                 "operator": "estimate", "confidence": 0.95,
             }},
        ],
    })

    # Without include_superseded: step-old only appears as a bare citation.
    without = await visualize_graph(
        runtime, {"session_id": session.session_id, "mode": "inference"}
    )
    mermaid = without["mermaid"]
    assert '-.->|"cites"|' in mermaid
    assert '(superseded)' not in mermaid
    assert '-.->|"superseded_by"|' not in mermaid

    # With include_superseded: step-old gets its full entry, upgraded from
    # the bare citation placeholder, plus its revision-history edges.
    result = await visualize_graph(runtime, {
        "session_id": session.session_id,
        "mode": "inference",
        "include_superseded": True,
    })
    mermaid = result["mermaid"]
    assert '"estimate, confidence 0.5 (superseded)"' in mermaid
    assert '-.->|"cites"|' in mermaid
    assert '-.->|"superseded"|' in mermaid
    assert '-.->|"superseded_by"|' in mermaid


async def test_visualize_graph_inference_mode_respects_max_objects():
    from cks import parse

    from cks_mcp.tools.evolve.handler import evolve_knowledge
    from cks_mcp.tools.visualize_graph.handler import visualize_graph

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "fact-1", "type": "Claim", "name": "P1"}, "structure": {}},'
        '{"identity": {"id": "fact-2", "type": "Claim", "name": "P2"}, "structure": {}},'
        '{"identity": {"id": "concl-1", "type": "Claim", "name": "C"}, "structure": {}}'
        ']}'
    )
    session = await runtime.create_session(structure)
    await evolve_knowledge(runtime, {
        "session_id": session.session_id,
        "operations": [
            {"type": "record_inference",
             "identity": {"id": "step-1", "type": "InferenceStep", "name": "s1"},
             "structure": {
                 "premises": ["fact-1", "fact-2"], "conclusion": "concl-1",
                 "operator": "deductive", "confidence": 0.9,
             }},
        ],
    })

    result = await visualize_graph(runtime, {
        "session_id": session.session_id, "mode": "inference", "max_objects": 2,
    })
    assert result["returned_nodes"] == 2
    assert result["is_truncated"] is True
    assert result["total_found_nodes"] > result["returned_nodes"]


async def test_visualize_graph_inference_mode_unsupported_core():
    from cks import parse
    from cks_runtime.runtime import Runtime

    from cks_mcp.tools.visualize_graph.handler import visualize_graph

    runtime = Runtime(core=None)
    structure = parse(VALID_KNOWLEDGE_JSON)
    session = await runtime.create_session(structure)

    result = await visualize_graph(
        runtime, {"session_id": session.session_id, "mode": "inference"}
    )
    assert result["error"] == "internal_error"
    assert "explain_inference" in result["message"]


async def test_visualize_graph_sanitizes_special_characters():
    from cks import parse

    from cks_mcp.tools.visualize_graph.handler import visualize_graph

    runtime = _real_runtime()
    weird_id = 'urn:concept:weird id (test)'
    structure = parse(json.dumps({
        "objects": [
            {"identity": {"id": weird_id, "type": "Concept", "name": 'Weird "Quoted" Name'}, "structure": {}},
            {"identity": {"id": "obj-2", "type": "Concept", "name": "Other"}, "structure": {}},
            {"identity": {"id": "rel-1", "type": "Relation", "name": "r"},
             "structure": {"participants": [weird_id, "obj-2"], "relation_type": "relates_to"}},
        ]
    }))
    session = await runtime.create_session(structure)
    result = await visualize_graph(runtime, {"session_id": session.session_id})

    mermaid = result["mermaid"]
    assert f"{weird_id}[" not in mermaid
    assert weird_id not in mermaid.split("\n")[1].split("[")[0]
    assert '#quot;Quoted#quot;' in mermaid
    assert '\\"' not in mermaid
    for line in mermaid.split("\n")[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        assert stripped.endswith(']') or '-->' in stripped