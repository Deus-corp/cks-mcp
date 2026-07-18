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
    # Имитация коммита
    runtime.create_session.return_value = MagicMock(session_id="s1", diagnostics=[])
    runtime.begin_transaction.return_value = MagicMock()
    runtime.commit_transaction.return_value = MagicMock(version_id="v1")
    return runtime


def test_validate_knowledge(mock_runtime):
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = validate_knowledge(mock_runtime, args)
    assert result["valid"] == True
    assert result["version_id"] == "v1"
    assert result["session_id"] == "s1"
    mock_runtime.create_session.assert_called_once()
    mock_runtime.commit_transaction.assert_called_once()


def test_serialize_knowledge(mock_runtime):
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = serialize_knowledge(mock_runtime, args)
    assert result == '{"serialized":true}'
    mock_runtime.create_session.assert_called_once()
    mock_runtime.commit_transaction.assert_called_once()


def test_explain_knowledge(mock_runtime):
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = explain_knowledge(mock_runtime, args)
    assert result["object_count"] == 1
    assert result["version_id"] == "v1"
    assert result["session_id"] == "s1"
    mock_runtime.create_session.assert_called_once()
    mock_runtime.commit_transaction.assert_called_once()


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