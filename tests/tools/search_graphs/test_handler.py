"""Unit tests for the search_graphs MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.search_graphs.handler import search_graphs

pytestmark = pytest.mark.asyncio

_GRAPHS = [
    {
        "name": "proj-alpha",
        "session_id": "s1",
        "description": "Alpha project knowledge graph",
        "tags": "alpha,demo",
        "public": True,
    },
    {
        "name": "proj-beta",
        "session_id": "s2",
        "description": "Beta rollout notes",
        "tags": "beta",
        "public": False,
    },
    {
        "name": "misc",
        "session_id": "s3",
        "description": "",
        "tags": "alpha-adjacent",
        "public": True,
    },
]


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.list_graphs = AsyncMock(return_value=_GRAPHS)
    return runtime


async def test_empty_query_rejected(mock_runtime):
    result = await search_graphs(mock_runtime, {"query": ""})
    assert result.get("error") == "empty_query"
    mock_runtime.storage.list_graphs.assert_not_called()


async def test_whitespace_query_rejected(mock_runtime):
    result = await search_graphs(mock_runtime, {"query": "   "})
    assert result.get("error") == "empty_query"


async def test_missing_query_rejected(mock_runtime):
    result = await search_graphs(mock_runtime, {})
    assert result.get("error") == "empty_query"


async def test_matches_name(mock_runtime):
    result = await search_graphs(mock_runtime, {"query": "proj-alpha"})
    assert [g["name"] for g in result["graphs"]] == ["proj-alpha"]


async def test_matches_description_case_insensitive(mock_runtime):
    result = await search_graphs(mock_runtime, {"query": "ROLLOUT"})
    assert [g["name"] for g in result["graphs"]] == ["proj-beta"]


async def test_matches_tags_substring_across_multiple(mock_runtime):
    result = await search_graphs(mock_runtime, {"query": "alpha"})
    names = {g["name"] for g in result["graphs"]}
    assert names == {"proj-alpha", "misc"}


async def test_no_match(mock_runtime):
    result = await search_graphs(mock_runtime, {"query": "nonexistent"})
    assert result == {"graphs": []}


async def test_passes_tag_and_public_only_through_to_list_graphs(mock_runtime):
    await search_graphs(mock_runtime, {"query": "alpha", "tag": "demo", "public_only": True})
    mock_runtime.storage.list_graphs.assert_awaited_once_with("demo", True, team=None)


async def test_defaults_tag_none_and_public_only_false(mock_runtime):
    await search_graphs(mock_runtime, {"query": "alpha"})
    mock_runtime.storage.list_graphs.assert_awaited_once_with(None, False, team=None)


async def test_team_passed_through(mock_runtime):
    await search_graphs(mock_runtime, {"query": "alpha", "team": "acme-eng"})
    mock_runtime.storage.list_graphs.assert_awaited_once_with(None, False, team="acme-eng")