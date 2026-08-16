"""Unit tests for the unregister_graph MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.unregister_graph.handler import unregister_graph

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.unregister_graph = AsyncMock(return_value=True)
    return runtime


async def test_missing_name(mock_runtime):
    result = await unregister_graph(mock_runtime, {})
    assert result.get("error") == "missing_parameter"
    mock_runtime.storage.unregister_graph.assert_not_called()


async def test_unregisters_graph(mock_runtime):
    result = await unregister_graph(mock_runtime, {"name": "proj-a"})

    assert result == {"unregistered": True, "name": "proj-a"}
    mock_runtime.storage.unregister_graph.assert_awaited_once_with("proj-a")


async def test_graph_not_found(mock_runtime):
    mock_runtime.storage.unregister_graph = AsyncMock(return_value=False)

    result = await unregister_graph(mock_runtime, {"name": "missing"})

    assert result.get("error") == "graph_not_found"
    mock_runtime.storage.unregister_graph.assert_awaited_once_with("missing")