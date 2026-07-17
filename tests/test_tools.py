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

# Minimal valid Knowledge Structure JSON
VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    # Мокируем все методы core_bridge
    runtime.core_bridge.validate.return_value = MagicMock(
        valid=True, diagnostics=[], metadata={}
    )
    runtime.core_bridge.serialize.return_value = '{"serialized":true}'
    runtime.core_bridge.explain.return_value = {"summary": "test"}
    runtime.core_bridge.evolve.return_value = {"evolved": True}
    return runtime


def test_validate_knowledge(mock_runtime):
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = validate_knowledge(mock_runtime, args)
    assert result["valid"] == True
    mock_runtime.core_bridge.validate.assert_called_once()


def test_serialize_knowledge(mock_runtime):
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = serialize_knowledge(mock_runtime, args)
    # result – это строка JSON, которую вернул core_bridge.serialize
    data = json.loads(result)
    assert data["serialized"] == True
    mock_runtime.core_bridge.serialize.assert_called_once()


def test_explain_knowledge(mock_runtime):
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = explain_knowledge(mock_runtime, args)
    assert result["summary"] == "test"
    mock_runtime.core_bridge.explain.assert_called_once()


def test_evolve_knowledge(mock_runtime):
    args = {
        "json_data": VALID_KNOWLEDGE_JSON,
        "operations": [{"add": "node"}],
    }
    result = evolve_knowledge(mock_runtime, args)
    assert result["evolved"] == True
    mock_runtime.core_bridge.evolve.assert_called_once()


def test_validate_knowledge_with_invalid_json(mock_runtime):
    args = {"json_data": "not valid json"}
    with pytest.raises(Exception):
        validate_knowledge(mock_runtime, args)