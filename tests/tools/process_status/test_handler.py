"""Unit tests for the process_status MCP tool."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from cks_runtime.storage.storage import AgentLivenessRecord

from cks_mcp.tools.process_status.handler import process_status

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


async def test_never_seen_process_kind(mock_runtime):
    result = await process_status(mock_runtime, {"process_kind": "pipeline"})

    assert result == {"process_kind": "pipeline", "found": False}


async def test_found_matching_kind(mock_runtime):
    rec = _record(process_kind="enrichment", instance_id="inst-9")
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[rec])

    result = await process_status(mock_runtime, {"process_kind": "enrichment"})

    assert "found" not in result  # no "found" key on the success path
    assert result["instance_id"] == "inst-9"
    assert result["process_kind"] == "enrichment"
    assert result["status"] == "alive"


async def test_picks_first_matching_record_most_recent(mock_runtime):
    # list_agent_liveness is documented to return most-recently-started
    # first; process_status should return the first match, not scan for
    # the "best" one.
    newest = _record(process_kind="critic", instance_id="inst-newest")
    older = _record(process_kind="critic", instance_id="inst-older")
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[newest, older])

    result = await process_status(mock_runtime, {"process_kind": "critic"})

    assert result["instance_id"] == "inst-newest"


async def test_skips_non_matching_kinds(mock_runtime):
    other = _record(process_kind="pipeline", instance_id="inst-pipeline")
    match = _record(process_kind="fork_resolution", instance_id="inst-fork")
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[other, match])

    result = await process_status(mock_runtime, {"process_kind": "fork_resolution"})

    assert result["instance_id"] == "inst-fork"


async def test_stopped_status_for_stale_heartbeat(mock_runtime):
    stale = (datetime.now(UTC) - timedelta(seconds=300)).isoformat()
    rec = _record(process_kind="pipeline", liveness_interval_s=30.0, last_heartbeat_at=stale)
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[rec])

    result = await process_status(mock_runtime, {"process_kind": "pipeline"})

    assert result["status"] == "stopped"


async def test_current_task_fields_pass_through(mock_runtime):
    rec = _record(
        process_kind="enrichment",
        current_task_id=7,
        current_task_type="enrichment_request",
    )
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[rec])

    result = await process_status(mock_runtime, {"process_kind": "enrichment"})

    assert result["current_task_id"] == 7
    assert result["current_task_type"] == "enrichment_request"
