"""Unit tests for the list_processes MCP tool."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from cks_runtime.storage.storage import AgentLivenessRecord

from cks_mcp.tools.list_processes.handler import list_processes

pytestmark = pytest.mark.asyncio


def _record(
    *,
    instance_id: str = "inst-1",
    process_kind: str = "critic",
    hostname: str = "host-a",
    pid: int = 123,
    liveness_interval_s: float = 30.0,
    started_at: str | None = None,
    last_heartbeat_at: str | None = None,
    current_task_id: int | None = None,
    current_task_type: str | None = None,
) -> AgentLivenessRecord:
    now = datetime.now(UTC)
    return AgentLivenessRecord(
        instance_id=instance_id,
        process_kind=process_kind,
        hostname=hostname,
        pid=pid,
        liveness_interval_s=liveness_interval_s,
        started_at=started_at or (now - timedelta(hours=1)).isoformat(),
        last_heartbeat_at=last_heartbeat_at or now.isoformat(),
        current_task_id=current_task_id,
        current_task_type=current_task_type,
    )


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.list_agent_liveness = AsyncMock(return_value=[])
    return runtime


async def test_empty_response(mock_runtime):
    result = await list_processes(mock_runtime, {})

    assert result == {"processes": []}
    mock_runtime.storage.list_agent_liveness.assert_awaited_once_with()


async def test_single_alive_process(mock_runtime):
    rec = _record()
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[rec])

    result = await list_processes(mock_runtime, {})

    assert len(result["processes"]) == 1
    entry = result["processes"][0]
    assert entry["instance_id"] == "inst-1"
    assert entry["process_kind"] == "critic"
    assert entry["hostname"] == "host-a"
    assert entry["pid"] == 123
    assert entry["status"] == "alive"


async def test_stopped_process_stale_heartbeat(mock_runtime):
    # liveness_interval_s=30 => TTL is 90s; put heartbeat well past that.
    stale = (datetime.now(UTC) - timedelta(seconds=300)).isoformat()
    rec = _record(liveness_interval_s=30.0, last_heartbeat_at=stale)
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[rec])

    result = await list_processes(mock_runtime, {})

    assert result["processes"][0]["status"] == "stopped"


async def test_malformed_last_heartbeat_is_stopped(mock_runtime):
    rec = _record(last_heartbeat_at="not-a-date")
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[rec])

    result = await list_processes(mock_runtime, {})

    assert result["processes"][0]["status"] == "stopped"


async def test_multiple_processes_preserve_order_and_task_fields(mock_runtime):
    rec1 = _record(instance_id="inst-1", process_kind="critic")
    rec2 = _record(
        instance_id="inst-2",
        process_kind="enrichment",
        current_task_id=42,
        current_task_type="enrichment_request",
    )
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[rec1, rec2])

    result = await list_processes(mock_runtime, {})

    assert [p["instance_id"] for p in result["processes"]] == ["inst-1", "inst-2"]
    assert result["processes"][1]["current_task_id"] == 42
    assert result["processes"][1]["current_task_type"] == "enrichment_request"
    assert result["processes"][0]["current_task_id"] is None


async def test_naive_timestamp_treated_as_utc(mock_runtime):
    # No timezone info (as SQLite storage tends to produce) -- should
    # still be interpreted as UTC rather than raising or mis-computing.
    naive_recent = datetime.now(UTC).replace(tzinfo=None).isoformat()
    rec = _record(liveness_interval_s=30.0, last_heartbeat_at=naive_recent)
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[rec])

    result = await list_processes(mock_runtime, {})

    assert result["processes"][0]["status"] == "alive"
