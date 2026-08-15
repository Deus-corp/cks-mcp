"""Unit tests for the list_graphs MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.list_graphs.handler import list_graphs

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.list_graphs = AsyncMock(return_value=[])
    return runtime


async def test_no_tag(mock_runtime):
    result = await list_graphs(mock_runtime, {})
    assert result == {"graphs": []}
    mock_runtime.storage.list_graphs.assert_awaited_once_with(None, False, team=None)


async def test_with_tag(mock_runtime):
    graphs = [
        {"name": "proj-a", "session_id": "s1", "description": "", "tags": "demo"},
    ]
    mock_runtime.storage.list_graphs = AsyncMock(return_value=graphs)

    result = await list_graphs(mock_runtime, {"tag": "demo"})

    assert result == {"graphs": graphs}
    mock_runtime.storage.list_graphs.assert_awaited_once_with("demo", False, team=None)


async def test_empty_tag_treated_as_none(mock_runtime):
    result = await list_graphs(mock_runtime, {"tag": ""})
    assert result == {"graphs": []}
    mock_runtime.storage.list_graphs.assert_awaited_once_with(None, False, team=None)


async def test_public_only(mock_runtime):
    result = await list_graphs(mock_runtime, {"public_only": True})
    assert result == {"graphs": []}
    mock_runtime.storage.list_graphs.assert_awaited_once_with(None, True, team=None)


async def test_tag_and_public_only_combined(mock_runtime):
    result = await list_graphs(mock_runtime, {"tag": "demo", "public_only": True})
    assert result == {"graphs": []}
    mock_runtime.storage.list_graphs.assert_awaited_once_with("demo", True, team=None)


async def test_team_passed_through(mock_runtime):
    result = await list_graphs(mock_runtime, {"team": "acme-eng"})
    assert result == {"graphs": []}
    mock_runtime.storage.list_graphs.assert_awaited_once_with(None, False, team="acme-eng")