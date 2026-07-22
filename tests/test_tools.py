"""Unit tests for MCP tool implementations."""

from __future__ import annotations

from unittest.mock import MagicMock
import json
import pytest

from cks_mcp.tools import (
    validate_knowledge,
    serialize_knowledge,
    explain_knowledge,
    evolve_knowledge,
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
    from cks_mcp.tools.compare import compare_versions
    from cks_runtime.versioning.version import RuntimeVersion

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