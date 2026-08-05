"""Unit tests for the check_graph_freshness MCP tool."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.check_graph_freshness.handler import check_graph_freshness

pytestmark = pytest.mark.asyncio

_TTL_SECONDS = 7 * 24 * 3600


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.get_graph = AsyncMock(return_value=None)
    runtime.config.graph_freshness_ttl_seconds = _TTL_SECONDS
    return runtime


async def test_missing_name(mock_runtime):
    result = await check_graph_freshness(mock_runtime, {})
    assert result.get("error") == "missing_parameter"
    mock_runtime.storage.get_graph.assert_not_called()


async def test_not_found(mock_runtime):
    result = await check_graph_freshness(mock_runtime, {"name": "unknown"})
    assert result == {"found": False}
    mock_runtime.storage.get_graph.assert_awaited_once_with("unknown")


async def test_fresh_graph(mock_runtime):
    recent = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    mock_runtime.storage.get_graph = AsyncMock(
        return_value={"name": "g1", "session_id": "s1", "updated_at": recent}
    )

    result = await check_graph_freshness(mock_runtime, {"name": "g1"})

    assert result == {"fresh": True}


async def test_outdated_graph(mock_runtime):
    stale = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    mock_runtime.storage.get_graph = AsyncMock(
        return_value={"name": "g1", "session_id": "s1", "updated_at": stale}
    )

    result = await check_graph_freshness(mock_runtime, {"name": "g1"})

    assert result["fresh"] is False
    assert result["last_updated"] == stale
    assert result["ttl_days"] == pytest.approx(7.0)


async def test_respects_configured_ttl(mock_runtime):
    mock_runtime.config.graph_freshness_ttl_seconds = 3600  # 1 hour
    two_hours_ago = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    mock_runtime.storage.get_graph = AsyncMock(
        return_value={"name": "g1", "session_id": "s1", "updated_at": two_hours_ago}
    )

    result = await check_graph_freshness(mock_runtime, {"name": "g1"})

    assert result["fresh"] is False
    assert result["ttl_days"] == pytest.approx(1 / 24)


async def test_sqlite_style_timestamp_without_timezone(mock_runtime):
    # SQLiteStorage stores updated_at as "YYYY-MM-DD HH:MM:SS" (no
    # timezone, no 'T'), unlike InMemoryStorage's isoformat().
    stale_naive = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    mock_runtime.storage.get_graph = AsyncMock(
        return_value={"name": "g1", "session_id": "s1", "updated_at": stale_naive}
    )

    result = await check_graph_freshness(mock_runtime, {"name": "g1"})

    assert result["fresh"] is False


async def test_malformed_updated_at(mock_runtime):
    mock_runtime.storage.get_graph = AsyncMock(
        return_value={"name": "g1", "session_id": "s1", "updated_at": "not-a-date"}
    )

    result = await check_graph_freshness(mock_runtime, {"name": "g1"})

    assert result["fresh"] is None
    assert result["last_updated"] == "not-a-date"
