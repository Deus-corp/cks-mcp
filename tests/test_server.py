"""Tests for MCP server via cks‑runtime."""
import json
import pytest
from cks_runtime.runtime import Runtime
from cks_runtime.adapters.mcp.handlers import MCPHandler
from cks_runtime_core import CksCoreAdapter


@pytest.fixture
def handler():
    runtime = Runtime(core=CksCoreAdapter())
    return MCPHandler(runtime)


@pytest.mark.asyncio
async def test_tools_list(handler):
    """tools/list should return available tools."""
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    response = await handler.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    tools = response["result"]
    assert len(tools) >= 1
    assert any(t["name"] == "validate_knowledge" for t in tools)


@pytest.mark.asyncio
async def test_tools_call_validate(handler):
    """tools/call for validate_knowledge should succeed with valid input."""
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "validate_knowledge",
            "arguments": {
                "json_data": json.dumps({
                    "objects": [
                        {
                            "identity": {"id": "obj-1", "type": "Definition", "name": "Test"},
                            "structure": {},
                        }
                    ]
                })
            },
        },
    }
    response = await handler.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 2
    result = json.loads(response["result"])
    assert result["valid"] is True


@pytest.mark.asyncio
async def test_tools_call_validate_invalid(handler):
    """tools/call for validate_knowledge should return error for invalid input."""
    request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "validate_knowledge",
            "arguments": {
                "json_data": json.dumps({
                    "objects": [
                        {"identity": {"id": "dup", "type": "X", "name": "x"}, "structure": {}},
                        {"identity": {"id": "dup", "type": "Y", "name": "y"}, "structure": {}},
                    ]
                })
            },
        },
    }
    response = await handler.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 3
    result = json.loads(response["result"])
    assert result["valid"] is False


@pytest.mark.asyncio
async def test_tools_call_unknown_tool(handler):
    """Calling an unknown tool should return an error."""
    request = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "nonexistent",
            "arguments": {},
        },
    }
    response = await handler.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 4
    assert "error" in response
    assert response["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_unknown_method(handler):
    """Calling an unknown method should return an error."""
    request = {"jsonrpc": "2.0", "id": 5, "method": "unknown/method", "params": {}}
    response = await handler.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 5
    assert "error" in response


@pytest.mark.asyncio
async def test_missing_method(handler):
    """Request with missing method should return an error."""
    request = {"jsonrpc": "2.0", "id": 6}
    response = await handler.handle_request(request)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 6
    assert "error" in response