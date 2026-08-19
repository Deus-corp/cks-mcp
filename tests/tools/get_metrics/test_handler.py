"""Unit tests for the get_metrics MCP tool."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cks_mcp.observability.llm_telemetry import llm_telemetry
from cks_mcp.tools.get_metrics.handler import get_metrics

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_llm_telemetry():
    llm_telemetry.reset()
    yield
    llm_telemetry.reset()


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.metrics.snapshot.return_value = {"sessions_created": 0}
    return runtime


async def test_get_metrics_includes_llm_telemetry_key(mock_runtime):
    result = await get_metrics(mock_runtime, {})

    assert "llm_telemetry" in result
    assert "runtime_metrics" in result
    assert "tool_telemetry" in result
    assert "critic_agent_metrics" in result


async def test_get_metrics_llm_telemetry_empty_by_default(mock_runtime):
    result = await get_metrics(mock_runtime, {})

    assert result["llm_telemetry"]["total_calls"] == 0
    assert result["llm_telemetry"]["total_cost_estimate"] == 0.0


async def test_get_metrics_llm_telemetry_reflects_recorded_calls(mock_runtime):
    llm_telemetry.record_call(
        "anthropic", "claude-sonnet-4-6", "construct_knowledge", 1500, 250.0, True,
        cost_estimate=0.0105,
    )
    llm_telemetry.record_call(
        "ollama", "llama3.2", "resolve_gossip_conflict", 300, 80.0, True,
    )

    result = await get_metrics(mock_runtime, {})

    llm_snap = result["llm_telemetry"]
    assert llm_snap["total_calls"] == 2
    assert llm_snap["calls_by_provider"] == {"anthropic": 1, "ollama": 1}
    assert llm_snap["calls_by_tool"] == {
        "construct_knowledge": 1,
        "resolve_gossip_conflict": 1,
    }
    assert llm_snap["total_tokens"] == 1800
    assert llm_snap["total_cost_estimate"] == pytest.approx(0.0105)
