"""Unit tests for the get_graph MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.get_graph.handler import get_graph

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.get_graph = AsyncMock(return_value=None)
    return runtime


async def test_missing_name(mock_runtime):
    result = await get_graph(mock_runtime, {})
    assert result.get("error") == "missing_parameter"
    mock_runtime.storage.get_graph.assert_not_called()


async def test_not_found(mock_runtime):
    result = await get_graph(mock_runtime, {"name": "unknown"})
    assert result == {"found": False}
    mock_runtime.storage.get_graph.assert_awaited_once_with("unknown")


async def test_found(mock_runtime):
    mock_runtime.storage.get_graph = AsyncMock(
        return_value={
            "name": "proj-a",
            "session_id": "s1",
            "description": "my graph",
            "tags": "demo",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-02T00:00:00",
        }
    )

    result = await get_graph(mock_runtime, {"name": "proj-a"})

    assert result["found"] is True
    assert result["name"] == "proj-a"
    assert result["session_id"] == "s1"
    assert result["description"] == "my graph"
    assert result["tags"] == "demo"
