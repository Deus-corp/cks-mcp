"""Unit tests for MCP tool implementations."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools import (
    evolve_knowledge,
    explain_knowledge,
    serialize_knowledge,
    validate_knowledge,
)

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)

pytestmark = pytest.mark.asyncio


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
    # Для evolve_knowledge нужно, чтобы core_bridge.evolve возвращал
    # объект, у которого есть .relations() (вызывается provenance)
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


async def test_validate_knowledge_valid(mock_runtime):
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = await validate_knowledge(mock_runtime, args)
    assert result["valid"] == True
    assert result["version_id"] == "v1"
    assert result["session_id"] == "s1"
    mock_runtime.create_session.assert_awaited_once()
    mock_runtime.commit_transaction.assert_awaited_once()


async def test_validate_knowledge_invalid(mock_runtime):
    from cks_runtime.diagnostics.diagnostic import (
        Diagnostic as RuntimeDiagnostic,
    )
    from cks_runtime.diagnostics.diagnostic import (
        DiagnosticSeverity,
        DiagnosticSource,
    )

    session = MagicMock(diagnostics=[], session_id="s1")
    mock_runtime.create_session = AsyncMock(return_value=session)
    tx = MagicMock(session=session)
    mock_runtime.begin_transaction.return_value = tx

    async def fake_commit(tx):
        tx.session.diagnostics.append(
            RuntimeDiagnostic(
                code="ERR-001",
                severity=DiagnosticSeverity.ERROR,
                source=DiagnosticSource.CORE,
                message="Invalid structure",
                metadata={"key": "value"},
            )
        )
        return MagicMock(version_id="v2")

    mock_runtime.commit_transaction = AsyncMock(side_effect=fake_commit)
    mock_runtime.executor.execute = AsyncMock(return_value=MagicMock(
        succeeded=True,
        payload={"evolved": True},
        status=MagicMock(value="completed")
    ))
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = await validate_knowledge(mock_runtime, args)
    assert result["valid"] is False
    assert result["version_id"] == "v2"
    assert len(result["diagnostics"]) == 1
    assert result["diagnostics"][0]["code"] == "ERR-001"
    assert result["diagnostics"][0]["severity"] == "error"


async def test_serialize_knowledge(mock_runtime):
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = await serialize_knowledge(mock_runtime, args)
    assert result == '{"serialized":true}'

async def test_explain_knowledge(mock_runtime):
    mock_runtime.begin_transaction.return_value.results = [
        MagicMock(payload={"object_count": 1, "relation_count": 0})
    ]
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = await explain_knowledge(mock_runtime, args)
    assert result["object_count"] == 1
    assert result["relation_count"] == 0


async def test_evolve_knowledge(mock_runtime):
    args = {
        "json_data": VALID_KNOWLEDGE_JSON,
        "operations": [
            {
                "type": "add_object",
                "identity": {"id": "obj-2", "type": "Lemma", "name": "New"},
                "structure": {},
            }
        ],
    }
    result = await evolve_knowledge(mock_runtime, args)
    assert result["evolved"] == True
    assert result["version_id"] == "v1"
    assert result["session_id"] == "s1"
    mock_runtime.create_session.assert_awaited_once()
    mock_runtime.commit_transaction.assert_awaited_once()


async def test_compare_versions(mock_runtime):
    from cks_runtime.versioning.version import RuntimeVersion

    from cks_mcp.tools.compare import compare_versions

    session = MagicMock(session_id="s1")
    session.version_history = [
        RuntimeVersion(session_id="s1", transaction_id="tx1", knowledge_structure={"test": True}, metadata={}, version_id="v1"),
        RuntimeVersion(session_id="s1", transaction_id="tx2", knowledge_structure={"test": True}, metadata={}, version_id="current_v"),
    ]
    mock_runtime.get_session.return_value = session
    mock_runtime.core_bridge.diff.return_value = []
    args = {"session_id": "s1", "target_version_id": "v1"}
    result = await compare_versions(mock_runtime, args)
    assert result["session_id"] == "s1"
    assert result["base_version_id"] == "v1"
    assert result["direction"] == "base_to_current"
    assert "summary" in result
    assert "operations" in result


async def test_query_subgraph_basic():
    """End-to-end test: create a session and extract a subgraph."""
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter

    from cks_mcp.tools.query_subgraph import query_subgraph_tool

    runtime = Runtime(core=CksCoreAdapter())

    from cks import parse
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "A", "type": "Node", "name": "a"}, "structure": {}},'
        '{"identity": {"id": "B", "type": "Node", "name": "b"}, "structure": {}},'
        '{"identity": {"id": "C", "type": "Node", "name": "c"}, "structure": {}},'
        '{"identity": {"id": "r1", "type": "Relation", "name": "r1"}, "structure": {"participants": ["A", "B"], "relation_type": "links"}},'
        '{"identity": {"id": "r2", "type": "Relation", "name": "r2"}, "structure": {"participants": ["B", "C"], "relation_type": "links"}}'
        ']}'
    )
    session = await runtime.create_session(structure)

    result = await query_subgraph_tool(runtime, {
        "session_id": session.session_id,
        "seed_ids": ["A"],
        "depth": 1
    })

    assert "subgraph" in result
    assert "total_found_nodes" in result
    assert result["total_found_nodes"] == 2  # A, B
    assert result["is_truncated"] == False

async def test_visualize_graph_missing_session_id(mock_runtime):
    from cks_mcp.tools.visualize_graph import visualize_graph
    result = await visualize_graph(mock_runtime, {})
    assert result["error"] == "missing_parameter"
    assert "session_id" in result["message"]


async def test_explain_diff_missing_parameters(mock_runtime):
    from cks_mcp.tools.explain_diff import explain_diff
    result = await explain_diff(mock_runtime, {})
    assert result["error"] == "missing_parameter"


async def test_suggest_evolution_missing_parameters(mock_runtime):
    from cks_mcp.tools.suggest_evolution import suggest_evolution
    result = await suggest_evolution(mock_runtime, {})
    assert result["error"] == "missing_parameter"


# ---------------------------------------------------------------------------
# End-to-end tests for visualize_graph, explain_diff, suggest_evolution
# (real Runtime + CksCoreAdapter, no mocks)
# ---------------------------------------------------------------------------

def _real_runtime():
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter
    return Runtime(core=CksCoreAdapter())


async def test_visualize_graph_basic():
    from cks import parse

    from cks_mcp.tools.visualize_graph import visualize_graph

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


async def test_visualize_graph_sanitizes_special_characters():
    from cks import parse

    from cks_mcp.tools.visualize_graph import visualize_graph

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


async def test_explain_diff_pure_add():
    from cks import parse

    from cks_mcp.tools.evolve import evolve_knowledge
    from cks_mcp.tools.explain_diff import explain_diff

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

    from cks_mcp.tools.evolve import evolve_knowledge
    from cks_mcp.tools.explain_diff import explain_diff

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


async def test_explain_diff_genuine_relation_content_change():
    from cks import parse

    from cks_mcp.tools.evolve import evolve_knowledge
    from cks_mcp.tools.explain_diff import explain_diff

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


async def test_suggest_evolution_basic():
    from cks import parse

    from cks_mcp.tools.suggest_evolution import suggest_evolution

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


async def test_export_knowledge_missing_session_id(mock_runtime):
    from cks_mcp.tools.export_knowledge import export_knowledge
    result = await export_knowledge(mock_runtime, {})
    assert result["error"] == "missing_parameter"
    assert "session_id" in result["message"]


async def test_suggest_evolution_preview_valid_operations():
    from cks import parse

    from cks_mcp.tools.suggest_evolution import suggest_evolution

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

    from cks_mcp.tools.suggest_evolution import suggest_evolution

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
    from cks_mcp.tools.suggest_evolution import suggest_evolution

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


# ---------------------------------------------------------------------------
# detect_contradictions
# ---------------------------------------------------------------------------

async def test_detect_contradictions_no_session_no_conflicts():
    from cks_mcp.tools.detect_contradictions import detect_contradictions

    runtime = _real_runtime()
    result = await detect_contradictions(runtime, {
        "json_data": '{"objects":[{"identity":{"id":"obj-1","type":"Concept","name":"A"},"structure":{}}]}'
    })
    assert result["contradiction_count"] == 0
    assert result["contradictions"] == []


async def test_detect_contradictions_with_session_no_conflicts():
    from cks import parse

    from cks_mcp.tools.detect_contradictions import detect_contradictions

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

    from cks_mcp.tools.detect_contradictions import detect_contradictions

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

    from cks_mcp.tools.detect_contradictions import detect_contradictions

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


async def test_detect_contradictions_missing_json_data():
    from cks_mcp.tools.detect_contradictions import detect_contradictions

    runtime = _real_runtime()
    result = await detect_contradictions(runtime, {})
    assert "error" in result
    assert result["error"] == "missing_parameter"


# ---------------------------------------------------------------------------
# fork_sandbox
# ---------------------------------------------------------------------------

async def test_fork_sandbox_no_operations():
    from cks import parse

    from cks_mcp.tools.fork_sandbox import fork_sandbox

    runtime = _real_runtime()
    structure = parse(
        '{"objects":[{"identity":{"id":"obj-1","type":"Concept","name":"A"},"structure":{}}]}'
    )
    parent = await runtime.create_session(structure)
    result = await fork_sandbox(runtime, {
        "session_id": parent.session_id,
        "hypothesis": "test sandbox"
    })
    assert "sandbox_session_id" in result
    assert result["parent_session_id"] == parent.session_id
    assert result["operations_applied"] == 0
    assert result["diff_from_fork_point"]["summary"]["added_objects"] == 0
    assert result["diff_from_fork_point"]["summary"]["removed_objects"] == 0
    assert parent.knowledge_structure is not None
    assert len(parent.knowledge_structure.objects) == 1


async def test_fork_sandbox_with_valid_operations():
    from cks import parse

    from cks_mcp.tools.fork_sandbox import fork_sandbox

    runtime = _real_runtime()
    structure = parse(
        '{"objects":[{"identity":{"id":"obj-1","type":"Concept","name":"A"},"structure":{}}]}'
    )
    parent = await runtime.create_session(structure)
    result = await fork_sandbox(runtime, {
        "session_id": parent.session_id,
        "hypothesis": "add object B",
        "operations": [
            {"type": "add_object", "identity": {"id": "obj-2", "type": "Concept", "name": "B"}, "structure": {}}
        ]
    })
    assert result["operations_applied"] == 1
    assert result["diff_from_fork_point"]["summary"]["added_objects"] == 1
    assert len(parent.knowledge_structure.objects) == 1
    sandbox = runtime.get_session(result["sandbox_session_id"])
    assert sandbox is not None
    assert len(sandbox.knowledge_structure.objects) == 2


async def test_fork_sandbox_invalid_operations():
    from cks import parse

    from cks_mcp.tools.fork_sandbox import fork_sandbox

    runtime = _real_runtime()
    structure = parse(
        '{"objects":[{"identity":{"id":"obj-1","type":"Concept","name":"A"},"structure":{}}]}'
    )
    parent = await runtime.create_session(structure)
    result = await fork_sandbox(runtime, {
        "session_id": parent.session_id,
        "operations": [{"type": "add_object", "identity": {"id": "obj-1", "type": "Concept", "name": "duplicate"}}]
    })
    assert "error" in result
    assert result["error"] == "evolution_failed"
    sandbox_id = result.get("sandbox_session_id")
    if sandbox_id:
        assert runtime.get_session(sandbox_id) is None
    assert len(parent.knowledge_structure.objects) == 1


async def test_fork_sandbox_missing_session_id():
    from cks_mcp.tools.fork_sandbox import fork_sandbox

    runtime = _real_runtime()
    result = await fork_sandbox(runtime, {})
    assert result["error"] == "missing_parameter"


# ---------------------------------------------------------------------------
# ingest_document
# ---------------------------------------------------------------------------

async def test_ingest_document_missing_url():
    from cks_mcp.tools.ingest_document import ingest_document
    runtime = _real_runtime()
    result = await ingest_document(runtime, {})
    assert result["error"] == "missing_parameter"

async def test_ingest_document_unsafe_url():
    from cks_mcp.tools.ingest_document import ingest_document
    runtime = _real_runtime()
    result = await ingest_document(runtime, {"url": "http://127.0.0.1/"})
    assert result["error"] == "unsafe_url"

async def test_ingest_document_valid_url(monkeypatch):
    """Simulate a real HTTP response and check the output structure."""
    import socket

    from cks_mcp.tools.ingest_document import ingest_document

    runtime = _real_runtime()

    class FakeResponse:
        text = "<html><head><title>Test Title</title><meta name='description' content='A test page'></head><body><p>knowledge graph structure canonical</p></body></html>"
        status_code = 200
        def raise_for_status(self): pass

    # Мокаем _safe_request, которая теперь используется вместо requests.get
    def fake_safe_request(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(
        "cks_mcp.tools.ingest_document._safe_request", fake_safe_request
    )
    # Также нужно замокать DNS, чтобы _resolve_and_validate_host не упал
    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return [(2, 1, 6, '', ('93.184.216.34', 0))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    result = await ingest_document(runtime, {"url": "https://example.com/"})
    assert "knowledge_structure" in result
    assert result["title"] == "Test Title"
    keywords = result["keywords"]
    assert len(keywords) > 0
    assert "canonical" in keywords
    assert result["relation_count"] == len(keywords)
    assert result["object_count"] == 1 + len(keywords) * 2

# ---------------------------------------------------------------------------
# BUG-02 regression tests: doc_id collision in ingest_document
# ---------------------------------------------------------------------------

class TestDocIdUnit:
    """Pure-unit tests for doc_id generation (sync, no asyncio needed)."""

    def _make_id(self, url: str) -> str:
        import hashlib
        import re
        _url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
        _safe_prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", url)[:30]
        return f"doc-{_safe_prefix}-{_url_hash}"

    def test_doc_id_no_collision_for_long_urls(self):
        """
        BUG-02: the old re.sub(...)[:50] sliced the *substituted* string,
        so two URLs differing only after their ~43rd raw character produced
        identical doc_ids.  The fix adds a 12-char SHA-256 suffix that makes
        every distinct URL yield a distinct id.
        """
        url1 = "https://example.com/very/long/path/that/exceeds/fifty/characters/page1"
        url2 = "https://example.com/very/long/path/that/exceeds/fifty/characters/page2"
        id1, id2 = self._make_id(url1), self._make_id(url2)
        assert id1 != id2, f"BUG-02 still present: both URLs produce doc_id='{id1}'"

    def test_doc_id_is_deterministic(self):
        """Same URL must always produce the same doc_id (no randomness)."""
        url = "https://docs.example.org/api/v2/reference"
        assert self._make_id(url) == self._make_id(url)

    def test_doc_id_contains_only_valid_cks_chars(self):
        """doc_id must only contain characters valid for CKS identity ids."""
        import re
        tricky_urls = [
            "https://example.com/path?q=hello&lang=en#section",
            "https://xn--nxasmq6b.com/日本語",
            "https://example.com/" + "a" * 200,
        ]
        for url in tricky_urls:
            doc_id = self._make_id(url)
            assert re.match(r"^[a-zA-Z0-9_-]+$", doc_id), (
                f"doc_id '{doc_id}' contains invalid characters for URL: {url[:60]}"
            )


@pytest.mark.asyncio
async def test_ingest_two_long_urls_no_collision(monkeypatch):
    """
    End-to-end: ingesting two URLs that would have collided under the old
    scheme must produce two distinct doc_ids and not raise
    'Duplicate canonical identity'.
    """
    import json
    import socket

    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter

    from cks_mcp.tools.ingest_document import ingest_document

    runtime = Runtime(core=CksCoreAdapter())

    class FakeResp:
        text = "<html><title>Page</title><body>content canonical knowledge</body></html>"
        def raise_for_status(self): pass

    monkeypatch.setattr("cks_mcp.tools.ingest_document._safe_request", lambda *a, **kw: FakeResp())
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 0))])

    url1 = "https://example.com/very/long/path/that/exceeds/fifty/characters/page1"
    url2 = "https://example.com/very/long/path/that/exceeds/fifty/characters/page2"

    result1 = await ingest_document(runtime, {"url": url1})
    result2 = await ingest_document(runtime, {"url": url2})

    assert "knowledge_structure" in result1, f"result1 error: {result1}"
    assert "knowledge_structure" in result2, f"result2 error: {result2}"

    # core_bridge.serialize returns a JSON string; parse it to inspect ids.
    ks1 = json.loads(result1["knowledge_structure"])
    ks2 = json.loads(result2["knowledge_structure"])
    doc_ids_1 = {o["identity"]["id"] for o in ks1["objects"] if o["identity"]["type"] == "Document"}
    doc_ids_2 = {o["identity"]["id"] for o in ks2["objects"] if o["identity"]["type"] == "Document"}

    assert doc_ids_1.isdisjoint(doc_ids_2), (
        f"BUG-02: both ingests produced the same Document id: "
        f"{doc_ids_1 & doc_ids_2}"
    )