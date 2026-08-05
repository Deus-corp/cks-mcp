"""Unit tests for MCP server request handling."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.server import handle_request

pytestmark = pytest.mark.asyncio

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)


class FakeSession:
    def __init__(self):
        self.session_id = "s1"
        self.diagnostics = []


class FakeVersion:
    def __init__(self):
        self.version_id = "v1"


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
    runtime.create_session = AsyncMock(return_value=FakeSession())
    runtime.begin_transaction.return_value = MagicMock()
    runtime.commit_transaction = AsyncMock(return_value=FakeVersion())
    return runtime


async def test_initialize(mock_runtime):
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    response = await handle_request(mock_runtime, request)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert "result" in response
    assert response["result"]["serverInfo"]["name"] == "cks-mcp"


async def test_ping(mock_runtime):
    request = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    response = await handle_request(mock_runtime, request)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 2
    assert "result" in response


async def test_tools_list(mock_runtime):
    request = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
    response = await handle_request(mock_runtime, request)
    tools = response["result"]["tools"]
    assert len(tools) == 46
    assert any(t["name"] == "validate_knowledge" for t in tools)


async def test_tools_call_validate(mock_runtime):
    request = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "validate_knowledge",
            "arguments": {"json_data": VALID_KNOWLEDGE_JSON},
        },
    }
    response = await handle_request(mock_runtime, request)
    assert "result" in response
    content = response["result"]["content"][0]["text"]
    result = json.loads(content)
    assert result["valid"] == True
    assert result["version_id"] == "v1"


async def test_tools_call_unknown_tool(mock_runtime):
    request = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {"name": "nonexistent", "arguments": {}},
    }
    response = await handle_request(mock_runtime, request)
    assert "error" in response
    assert response["error"]["code"] == -32601


async def test_unknown_method(mock_runtime):
    request = {"jsonrpc": "2.0", "id": 6, "method": "unknown"}
    response = await handle_request(mock_runtime, request)
    assert "error" in response
    assert response["error"]["code"] == -32601


async def test_observability_decorator_does_not_break_handler():
    from cks_mcp.observability import log_tool_call

    @log_tool_call("test_tool")
    async def fake_handler(runtime, arguments):
        return {"ok": True}

    result = await fake_handler(None, {})
    assert result == {"ok": True}


async def test_setup_event_subscriptions_does_not_raise():
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter

    from cks_mcp.observability import setup_event_subscriptions

    runtime = Runtime(core=CksCoreAdapter())
    setup_event_subscriptions(runtime)
    await runtime.aclose()