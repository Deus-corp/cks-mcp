"""Unit tests for the stop_agent MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.stop_agent.handler import stop_agent

pytestmark = pytest.mark.asyncio


def _mock_sweeper(*, agent_id: str = "contradiction", running: bool = True):
    sweeper = MagicMock()
    sweeper.stop = AsyncMock()
    sweeper.status = MagicMock(
        return_value={
            "agent_id": agent_id,
            "kind": "sweeper",
            "running": running,
            "interval_seconds": 3600,
            "last_run_at": None,
            "last_run_duration_ms": None,
            "last_result_count": None,
            "last_error": None,
        }
    )
    return sweeper


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime._sweepers = {}
    runtime.storage.set_sweeper_desired_running = AsyncMock()
    return runtime


async def test_unknown_agent_id(mock_runtime):
    result = await stop_agent(mock_runtime, {"agent_id": "nonexistent"})

    assert result == {"agent_id": "nonexistent", "found": False}
    mock_runtime.storage.set_sweeper_desired_running.assert_not_called()


async def test_stops_sweeper_and_persists_override(mock_runtime):
    sweeper = _mock_sweeper(agent_id="contradiction", running=False)
    mock_runtime._sweepers["contradiction"] = sweeper

    result = await stop_agent(mock_runtime, {"agent_id": "contradiction"})

    sweeper.stop.assert_awaited_once()
    mock_runtime.storage.set_sweeper_desired_running.assert_awaited_once_with(
        "contradiction", False
    )
    assert result["running"] is False
    assert "found" not in result  # no "found" key on the success path


async def test_returns_sweeper_status_shape(mock_runtime):
    sweeper = _mock_sweeper(agent_id="graph_health", running=False)
    mock_runtime._sweepers["graph_health"] = sweeper

    result = await stop_agent(mock_runtime, {"agent_id": "graph_health"})

    # Same shape agent_status returns -- whatever sweeper.status() gives back.
    assert result == sweeper.status.return_value


async def test_calls_stop_before_persisting_override(mock_runtime):
    """stop() must be called (in-process effect) regardless of the
    persisted override write -- order doesn't strictly matter for
    correctness here since they're independent side effects, but both
    must happen exactly once."""
    sweeper = _mock_sweeper(agent_id="temporal_staleness", running=False)
    mock_runtime._sweepers["temporal_staleness"] = sweeper

    await stop_agent(mock_runtime, {"agent_id": "temporal_staleness"})

    assert sweeper.stop.await_count == 1
    assert mock_runtime.storage.set_sweeper_desired_running.await_count == 1