"""Unit tests for the request_process_stop MCP tool."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from cks_runtime.storage.storage import AgentLivenessRecord

from cks_mcp.tools.request_process_stop.handler import request_process_stop

pytestmark = pytest.mark.asyncio


def _record(
    *,
    instance_id: str = "inst-1",
    process_kind: str = "critic",
    started_at: str | None = None,
    last_heartbeat_at: str | None = None,
) -> AgentLivenessRecord:
    now = datetime.now(UTC)
    return AgentLivenessRecord(
        instance_id=instance_id,
        process_kind=process_kind,
        hostname="host-a",
        pid=123,
        liveness_interval_s=30.0,
        started_at=started_at or (now - timedelta(hours=1)).isoformat(),
        last_heartbeat_at=last_heartbeat_at or now.isoformat(),
    )


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.list_agent_liveness = AsyncMock(return_value=[])
    runtime.storage.request_agent_stop = AsyncMock(return_value=True)
    return runtime


async def test_never_seen_process_kind(mock_runtime):
    result = await request_process_stop(mock_runtime, {"process_kind": "pipeline"})

    assert result == {"process_kind": "pipeline", "found": False}
    mock_runtime.storage.request_agent_stop.assert_not_called()


async def test_found_matching_kind_requests_stop(mock_runtime):
    rec = _record(process_kind="enrichment", instance_id="inst-9")
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[rec])

    result = await request_process_stop(mock_runtime, {"process_kind": "enrichment"})

    mock_runtime.storage.request_agent_stop.assert_awaited_once_with("inst-9")
    assert result == {
        "process_kind": "enrichment",
        "instance_id": "inst-9",
        "accepted": True,
    }
    assert "found" not in result  # no "found" key on the success path


async def test_picks_first_matching_record_most_recent(mock_runtime):
    # list_agent_liveness is documented to return most-recently-started
    # first; request_process_stop should target the first match.
    newest = _record(process_kind="critic", instance_id="inst-newest")
    older = _record(process_kind="critic", instance_id="inst-older")
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[newest, older])

    result = await request_process_stop(mock_runtime, {"process_kind": "critic"})

    mock_runtime.storage.request_agent_stop.assert_awaited_once_with("inst-newest")
    assert result["instance_id"] == "inst-newest"


async def test_skips_non_matching_kinds(mock_runtime):
    other = _record(process_kind="pipeline", instance_id="inst-pipeline")
    match = _record(process_kind="fork_resolution", instance_id="inst-fork")
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[other, match])

    result = await request_process_stop(
        mock_runtime, {"process_kind": "fork_resolution"}
    )

    mock_runtime.storage.request_agent_stop.assert_awaited_once_with("inst-fork")
    assert result["instance_id"] == "inst-fork"


async def test_accepted_reflects_storage_return_value(mock_runtime):
    """Edge case: the row disappeared between list_agent_liveness and
    request_agent_stop (e.g. storage wiped concurrently) -- accepted
    should reflect whatever request_agent_stop actually reports, not be
    hardcoded True."""
    rec = _record(process_kind="pipeline", instance_id="inst-gone")
    mock_runtime.storage.list_agent_liveness = AsyncMock(return_value=[rec])
    mock_runtime.storage.request_agent_stop = AsyncMock(return_value=False)

    result = await request_process_stop(mock_runtime, {"process_kind": "pipeline"})

    assert result["accepted"] is False