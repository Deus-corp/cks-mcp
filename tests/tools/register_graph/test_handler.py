"""Unit tests for the register_graph MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.register_graph.handler import register_graph

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.register_graph = AsyncMock()
    runtime.get_session = MagicMock(return_value=MagicMock())
    return runtime


async def test_missing_name(mock_runtime):
    result = await register_graph(mock_runtime, {"session_id": "s1"})
    assert result.get("error") == "missing_parameter"
    mock_runtime.storage.register_graph.assert_not_called()


async def test_missing_session_id(mock_runtime):
    result = await register_graph(mock_runtime, {"name": "proj-a"})
    assert result.get("error") == "missing_parameter"
    mock_runtime.storage.register_graph.assert_not_called()


async def test_session_not_found(mock_runtime):
    mock_runtime.get_session = MagicMock(return_value=None)

    result = await register_graph(mock_runtime, {"name": "proj-a", "session_id": "s1"})

    assert result.get("error") == "session_not_found"
    mock_runtime.storage.register_graph.assert_not_called()


async def test_registers_graph(mock_runtime):
    result = await register_graph(
        mock_runtime,
        {
            "name": "proj-a",
            "session_id": "s1",
            "description": "my graph",
            "tags": "demo,test",
        },
    )

    assert result == {
        "registered": True,
        "name": "proj-a",
        "public": False,
        "visibility": "private",
        "team": None,
    }
    mock_runtime.storage.register_graph.assert_awaited_once_with(
        name="proj-a", session_id="s1", description="my graph", tags="demo,test",
        public=False, source_graph_name=None, visibility=None, team=None,
    )


async def test_registers_graph_with_defaults(mock_runtime):
    result = await register_graph(mock_runtime, {"name": "proj-a", "session_id": "s1"})

    assert result == {
        "registered": True,
        "name": "proj-a",
        "public": False,
        "visibility": "private",
        "team": None,
    }
    mock_runtime.storage.register_graph.assert_awaited_once_with(
        name="proj-a", session_id="s1", description="", tags="", public=False,
        source_graph_name=None, visibility=None, team=None,
    )


async def test_registers_public_graph(mock_runtime):
    result = await register_graph(
        mock_runtime, {"name": "proj-a", "session_id": "s1", "public": True}
    )

    assert result == {
        "registered": True,
        "name": "proj-a",
        "public": True,
        "visibility": "public",
        "team": None,
    }
    mock_runtime.storage.register_graph.assert_awaited_once_with(
        name="proj-a", session_id="s1", description="", tags="", public=True,
        source_graph_name=None, visibility=None, team=None,
    )


async def test_registers_graph_with_source_graph_name(mock_runtime):
    result = await register_graph(
        mock_runtime,
        {"name": "proj-a-copy", "session_id": "s2", "source_graph_name": "proj-a"},
    )

    assert result == {
        "registered": True,
        "name": "proj-a-copy",
        "public": False,
        "visibility": "private",
        "team": None,
    }
    mock_runtime.storage.register_graph.assert_awaited_once_with(
        name="proj-a-copy", session_id="s2", description="", tags="", public=False,
        source_graph_name="proj-a", visibility=None, team=None,
    )


async def test_registers_team_graph(mock_runtime):
    result = await register_graph(
        mock_runtime,
        {
            "name": "proj-a",
            "session_id": "s1",
            "visibility": "team",
            "team": "acme-eng",
        },
    )

    assert result == {
        "registered": True,
        "name": "proj-a",
        "public": False,
        "visibility": "team",
        "team": "acme-eng",
    }
    mock_runtime.storage.register_graph.assert_awaited_once_with(
        name="proj-a", session_id="s1", description="", tags="", public=False,
        source_graph_name=None, visibility="team", team="acme-eng",
    )


async def test_rejects_invalid_visibility(mock_runtime):
    result = await register_graph(
        mock_runtime,
        {"name": "proj-a", "session_id": "s1", "visibility": "bogus"},
    )
    assert result.get("error") == "invalid_parameter"
    mock_runtime.storage.register_graph.assert_not_called()


async def test_rejects_team_visibility_without_team(mock_runtime):
    result = await register_graph(
        mock_runtime,
        {"name": "proj-a", "session_id": "s1", "visibility": "team"},
    )
    assert result.get("error") == "missing_parameter"
    mock_runtime.storage.register_graph.assert_not_called()