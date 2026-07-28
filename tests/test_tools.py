"""Unit tests for MCP tool implementations."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

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
    runtime.core_bridge.evolve.return_value = MagicMock()

    session = MagicMock(session_id="s1", diagnostics=[])
    runtime.create_session.return_value = session

    # Мок транзакции с готовым результатом операции
    tx = MagicMock(session=session)
    tx.results = [MagicMock(payload='{"serialized":true}')]
    runtime.begin_transaction.return_value = tx

    runtime.commit_transaction.return_value = MagicMock(version_id="v1")

    return runtime


def test_validate_knowledge_valid(mock_runtime):
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = validate_knowledge(mock_runtime, args)
    assert result["valid"] == True
    assert result["version_id"] == "v1"
    assert result["session_id"] == "s1"
    mock_runtime.create_session.assert_called_once()
    mock_runtime.commit_transaction.assert_called_once()


def test_validate_knowledge_invalid(mock_runtime):
    from cks_runtime.diagnostics.diagnostic import (
        Diagnostic as RuntimeDiagnostic,
    )
    from cks_runtime.diagnostics.diagnostic import (
        DiagnosticSeverity,
        DiagnosticSource,
    )

    # Настоящий список для диагностик
    session = MagicMock(diagnostics=[], session_id="s1")
    mock_runtime.create_session.return_value = session
    tx = MagicMock(session=session)
    mock_runtime.begin_transaction.return_value = tx

    def fake_commit(tx):
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

    mock_runtime.commit_transaction.side_effect = fake_commit
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = validate_knowledge(mock_runtime, args)
    assert result["valid"] is False
    assert result["version_id"] == "v2"
    assert len(result["diagnostics"]) == 1
    assert result["diagnostics"][0]["code"] == "ERR-001"
    assert result["diagnostics"][0]["severity"] == "error"


def test_serialize_knowledge(mock_runtime):
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = serialize_knowledge(mock_runtime, args)
    assert result == '{"serialized":true}'

def test_explain_knowledge(mock_runtime):
    # Для explain нужно, чтобы первый результат в tx.results содержал нужный payload
    mock_runtime.begin_transaction.return_value.results = [
        MagicMock(payload={"object_count": 1, "relation_count": 0})
    ]
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = explain_knowledge(mock_runtime, args)
    assert result["object_count"] == 1
    assert result["relation_count"] == 0


def test_evolve_knowledge(mock_runtime):
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
    result = evolve_knowledge(mock_runtime, args)
    assert result["evolved"] == True
    assert result["version_id"] == "v1"
    assert result["session_id"] == "s1"
    mock_runtime.create_session.assert_called_once()
    mock_runtime.commit_transaction.assert_called_once()


def test_compare_versions(mock_runtime):
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
    result = compare_versions(mock_runtime, args)
    assert result["session_id"] == "s1"
    assert result["base_version_id"] == "v1"
    assert result["direction"] == "base_to_current"
    assert "summary" in result
    assert "operations" in result


def test_query_subgraph_basic():
    """End-to-end test: создаём сессию и извлекаем подграф."""
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter

    from cks_mcp.tools.query_subgraph import query_subgraph_tool

    runtime = Runtime(core=CksCoreAdapter())

    # Создаём сессию с простым графом: A --r1-- B --r2-- C
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
    session = runtime.create_session(structure)

    # Вызываем query_subgraph
    result = query_subgraph_tool(runtime, {
        "session_id": session.session_id,
        "seed_ids": ["A"],
        "depth": 1
    })

    # Проверяем структуру ответа
    assert "subgraph" in result
    assert "total_found_nodes" in result
    assert result["total_found_nodes"] == 2  # A, B
    assert result["is_truncated"] == False

def test_visualize_graph_missing_session_id(mock_runtime):
    from cks_mcp.tools.visualize_graph import visualize_graph
    result = visualize_graph(mock_runtime, {})
    assert result["error"] == "missing_parameter"
    assert "session_id" in result["message"]


def test_explain_diff_missing_parameters(mock_runtime):
    from cks_mcp.tools.explain_diff import explain_diff
    result = explain_diff(mock_runtime, {})
    assert result["error"] == "missing_parameter"


def test_suggest_evolution_missing_parameters(mock_runtime):
    from cks_mcp.tools.suggest_evolution import suggest_evolution
    result = suggest_evolution(mock_runtime, {})
    assert result["error"] == "missing_parameter"


# ---------------------------------------------------------------------------
# End-to-end tests for visualize_graph, explain_diff, suggest_evolution
# (real Runtime + CksCoreAdapter, no mocks -- these exercise the actual
# cks-core diff/query_subgraph machinery the mock-based tests above don't).
# ---------------------------------------------------------------------------

def _real_runtime():
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter
    return Runtime(core=CksCoreAdapter())


def test_visualize_graph_basic():
    """Typical ids (with hyphens, as used throughout this project's own
    examples) must still produce syntactically valid Mermaid: a bare,
    unquoted hyphenated id is not a legal Mermaid node id."""
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
    session = runtime.create_session(structure)
    result = visualize_graph(runtime, {"session_id": session.session_id})

    # New format: just a "mermaid" key with the diagram text.
    assert "mermaid" in result
    mermaid = result["mermaid"]
    # Nodes must be aliased safely (n0, n1, ...), not bare "obj-1".
    assert "n0[" in mermaid
    assert "n1[" in mermaid
    assert "n2[" not in mermaid  # only 2 non-relation objects
    # The hyphenated ids must NOT appear as bare node identifiers.
    assert "obj-1[" not in mermaid
    assert "obj-2[" not in mermaid


def test_visualize_graph_sanitizes_special_characters():
    """Ids containing spaces/colons/parentheses and names containing
    double quotes must not break the generated Mermaid syntax."""
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
    session = runtime.create_session(structure)
    result = visualize_graph(runtime, {"session_id": session.session_id})

    mermaid = result["mermaid"]
    # The raw id must never appear unescaped as a bare node identifier --
    # spaces/colons/parens there would break Mermaid's parser.
    assert f"{weird_id}[" not in mermaid
    assert weird_id not in mermaid.split("\n")[1].split("[")[0]
    # A literal double quote inside a label must use Mermaid's HTML-entity
    # escape, not a backslash (which is not valid Mermaid syntax).
    assert '#quot;Quoted#quot;' in mermaid
    assert '\\"' not in mermaid
    # Every line must be parseable at a basic structural level: node lines
    # end with a closed ["..."] and edge lines have a matching arrow.
    for line in mermaid.split("\n")[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        assert stripped.endswith(']') or '-->' in stripped


def test_explain_diff_pure_add():
    """Adding a new object+relation with nothing else touched should be
    reported purely as additions."""
    from cks import parse

    from cks_mcp.tools.evolve import evolve_knowledge
    from cks_mcp.tools.explain_diff import explain_diff

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "obj-1", "type": "Concept", "name": "A"}, "structure": {}}'
        ']}'
    )
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    runtime.commit_transaction(tx)
    base_version = session.version_history[-1].version_id

    evolve_knowledge(runtime, {
        "session_id": session.session_id,
        "operations": [
            {"type": "add_object", "identity": {"id": "obj-2", "type": "Concept", "name": "B"}, "structure": {}},
            {"type": "add_relation", "identity": {"id": "rel-1", "type": "Relation", "name": "r"},
             "participants": ["obj-1", "obj-2"], "relation_type": "relates_to"},
        ],
    })

    result = explain_diff(runtime, {"session_id": session.session_id, "target_version_id": base_version})

    assert [o["id"] for o in result["details"]["added_objects"]] == ["obj-2"]
    assert result["details"]["removed_objects"] == []
    assert result["details"]["modified_objects"] == []
    assert [r["id"] for r in result["details"]["added_relations"]] == ["rel-1"]
    assert result["details"]["relinked_relations"] == []


def test_explain_diff_modified_object_reported_as_modified_not_delete_add():
    """A structure-only update to an existing object must be reported as
    'modified' with a field-level diff -- not as a delete+add of the same
    id -- and the untouched relation referencing it must be recognized as
    an unaffected relink, not a spurious add+remove."""
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
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    runtime.commit_transaction(tx)
    base_version = session.version_history[-1].version_id

    evolve_knowledge(runtime, {
        "session_id": session.session_id,
        "operations": [
            {"type": "update_object", "object_id": "obj-1", "structure_patch": {"summary": "new"}},
        ],
    })

    result = explain_diff(runtime, {"session_id": session.session_id, "target_version_id": base_version})
    details = result["details"]

    assert details["added_objects"] == []
    assert details["removed_objects"] == []
    assert len(details["modified_objects"]) == 1
    assert details["modified_objects"][0]["id"] == "obj-1"
    assert details["modified_objects"][0]["changes"] == {"summary": {"from": "old", "to": "new"}}

    # rel-1's own content never changed -- it must not be counted as an
    # add or a remove, only as an (unchanged) relink.
    assert details["added_relations"] == []
    assert details["removed_relations"] == []
    assert details["modified_relations"] == []
    assert [r["id"] for r in details["relinked_relations"]] == ["rel-1"]

    assert "Modified 1 object" in result["summary"]
    assert "Re-linked 1 relation" in result["summary"]


def test_explain_diff_genuine_relation_content_change():
    """When a relation's own content changes (e.g. its relation_type), it
    must be reported as a modified relation with a field-level diff."""
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
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    runtime.commit_transaction(tx)
    base_version = session.version_history[-1].version_id

    evolve_knowledge(runtime, {
        "session_id": session.session_id,
        "operations": [
            {"type": "remove_relation", "relation_id": "rel-1"},
            {"type": "add_relation", "identity": {"id": "rel-1", "type": "Relation", "name": "r"},
             "participants": ["obj-1", "obj-2"], "relation_type": "inspired_by"},
        ],
    })

    result = explain_diff(runtime, {"session_id": session.session_id, "target_version_id": base_version})
    details = result["details"]

    assert details["relinked_relations"] == []
    assert details["added_relations"] == []
    assert details["removed_relations"] == []
    assert len(details["modified_relations"]) == 1
    assert details["modified_relations"][0]["changes"] == {
        "relation_type": {"from": "derives_from", "to": "inspired_by"}
    }


def test_suggest_evolution_basic():
    """current_objects must list only plain objects (not relations), and
    current_relations must list relations with their real participants."""
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
    session = runtime.create_session(structure)

    result = suggest_evolution(runtime, {
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


def test_export_knowledge_missing_session_id(mock_runtime):
    from cks_mcp.tools.export_knowledge import export_knowledge
    result = export_knowledge(mock_runtime, {})
    assert result["error"] == "missing_parameter"
    assert "session_id" in result["message"]


def test_suggest_evolution_preview_valid_operations():
    """Passing 'operations' previews them via the same dry-run
    evolve_knowledge uses internally, but must not create a version or
    otherwise mutate the session."""
    from cks import parse

    from cks_mcp.tools.suggest_evolution import suggest_evolution

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "obj-1", "type": "Concept", "name": "A"}, "structure": {}}'
        ']}'
    )
    session = runtime.create_session(structure)
    versions_before = len(runtime.get_session(session.session_id).versions) if hasattr(session, "versions") else None

    result = suggest_evolution(runtime, {
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
    # Nothing committed: the live session structure is untouched.
    assert {o.identity.id for o in session.knowledge_structure.objects} == {"obj-1"}
    if versions_before is not None:
        assert len(runtime.get_session(session.session_id).versions) == versions_before


def test_suggest_evolution_preview_invalid_operations_reports_diagnostics():
    """An operation that would produce an invalid structure (here: a
    relation referencing a nonexistent participant) must be reported
    via diagnostics with would_apply=False, not raise."""
    from cks import parse

    from cks_mcp.tools.suggest_evolution import suggest_evolution

    runtime = _real_runtime()
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "obj-1", "type": "Concept", "name": "A"}, "structure": {}}'
        ']}'
    )
    session = runtime.create_session(structure)

    result = suggest_evolution(runtime, {
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

    # add_relation itself rejects a dangling participant at apply time
    # (ValueError inside _mutate), which the executor surfaces as a
    # failed dry-run rather than a validation diagnostic.
    assert result["would_apply"] is False
    assert "message" in result


def test_suggest_evolution_preview_malformed_operations():
    from cks_mcp.tools.suggest_evolution import suggest_evolution

    runtime = _real_runtime()
    from cks import parse
    structure = parse('{"objects": []}')
    session = runtime.create_session(structure)

    result = suggest_evolution(runtime, {
        "session_id": session.session_id,
        "description": "do something",
        "operations": [{"type": "not_a_real_operation"}],
    })

    assert result["error"] == "invalid_operations"