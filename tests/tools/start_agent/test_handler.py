"""Unit tests for the start_agent MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.start_agent.handler import start_agent

pytestmark = pytest.mark.asyncio


def _mock_sweeper(*, agent_id: str = "contradiction", running: bool = True):
    sweeper = MagicMock()
    sweeper.start = AsyncMock()
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
    result = await start_agent(mock_runtime, {"agent_id": "nonexistent"})

    assert result == {"agent_id": "nonexistent", "found": False}
    mock_runtime.storage.set_sweeper_desired_running.assert_not_called()


async def test_starts_sweeper_and_persists_override(mock_runtime):
    sweeper = _mock_sweeper(agent_id="contradiction", running=True)
    mock_runtime._sweepers["contradiction"] = sweeper

    result = await start_agent(mock_runtime, {"agent_id": "contradiction"})

    sweeper.start.assert_awaited_once()
    mock_runtime.storage.set_sweeper_desired_running.assert_awaited_once_with(
        "contradiction", True
    )
    assert result["running"] is True
    assert "found" not in result  # no "found" key on the success path


async def test_returns_sweeper_status_shape(mock_runtime):
    sweeper = _mock_sweeper(agent_id="graph_freshness", running=True)
    mock_runtime._sweepers["graph_freshness"] = sweeper

    result = await start_agent(mock_runtime, {"agent_id": "graph_freshness"})

    assert result == sweeper.status.return_value


async def test_disabled_sweeper_is_indistinguishable_from_unknown_id(mock_runtime):
    """A config-disabled sweeper was never constructed, so it's simply
    absent from runtime._sweepers -- same not-an-error convention as
    agent_status: this tool can't tell "unknown id" from "known but
    config-disabled" apart, by design (see schema docstring)."""
    result = await start_agent(mock_runtime, {"agent_id": "graph_auto_update"})

    assert result == {"agent_id": "graph_auto_update", "found": False}