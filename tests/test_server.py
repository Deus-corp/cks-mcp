"""Unit tests for MCP server request handling."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from cks_mcp.server import handle_request

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
    runtime.core_bridge.explain.return_value = {"summary": "test"}
    runtime.core_bridge.evolve.return_value = {"evolved": True}
    return runtime


def test_tools_list(mock_runtime):
    request = {"method": "tools/list"}
    response = handle_request(mock_runtime, request)
    tools = response["tools"]
    assert len(tools) == 4
    assert all("name" in t for t in tools)
    assert any(t["name"] == "validate_knowledge" for t in tools)


def test_tools_call_validate(mock_runtime):
    request = {
        "method": "tools/call",
        "params": {
            "name": "validate_knowledge",
            "arguments": {"json_data": VALID_KNOWLEDGE_JSON},
        },
    }
    response = handle_request(mock_runtime, request)
    assert "result" in response
    assert response["result"]["valid"] == True


def test_tools_call_unknown_tool(mock_runtime):
    request = {
        "method": "tools/call",
        "params": {"name": "nonexistent", "arguments": {}},
    }
    response = handle_request(mock_runtime, request)
    assert "error" in response
    assert "Unknown tool" in response["error"]


def test_unknown_method(mock_runtime):
    response = handle_request(mock_runtime, {"method": "unknown"})
    assert "error" in response