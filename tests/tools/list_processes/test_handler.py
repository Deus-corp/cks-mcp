"""Unit tests for the list_processes MCP tool."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from cks_runtime.storage.storage import AgentLivenessRecord

from cks_mcp.tools import list_processes as list_processes_module
from cks_mcp.tools.list_processes.handler import list_processes

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_prune_throttle_state():
    """Each test gets a clean slate for the module-level throttle/task
    globals (see _maybe_schedule_prune) so tests don't leak state into
    each other via real wall-clock time."""
    list_processes_module.handler._last_prune_attempt_monotonic = float("-inf")
    list_processes_module.handler._prune_task = None
    yield
    list_processes_module.handler._last_prune_attempt_monotonic = float("-inf")
    list_processes_module.handler._prune_task = None


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


async def test_list_processes_does_not_await_prune_inline(mock_runtime):
    """Regression test for issue #8 (process_status/list_processes
    sometimes taking 30+ seconds): the prune must be scheduled as a
    background task, never awaited directly inside list_processes, so
    a slow/blocked prune can't delay the read."""
    mock_runtime.storage.supports_agent_liveness = True
    prune_started = asyncio.Event()
    release_prune = asyncio.Event()

    async def slow_prune(_ttl):
        prune_started.set()
        await release_prune.wait()

    mock_runtime.storage.prune_agent_liveness = AsyncMock(side_effect=slow_prune)

    result = await asyncio.wait_for(list_processes(mock_runtime, {}), timeout=1.0)

    assert result == {"processes": []}
    # The prune may or may not have started yet (it's a fire-and-forget
    # task), but list_processes itself must already have returned.
    release_prune.set()
    await asyncio.wait_for(prune_started.wait(), timeout=1.0)
    # Let the background task actually finish so it doesn't leak
    # across tests / trigger "Task was destroyed but it is pending".
    task = list_processes_module.handler._prune_task
    if task is not None:
        await task


async def test_list_processes_throttles_repeated_prune_attempts(mock_runtime):
    """Back-to-back polls (studio's Agent Control Panel polls every
    few seconds) must not each reissue the prune DELETE -- only the
    first call within the throttle window should schedule one."""
    mock_runtime.storage.supports_agent_liveness = True
    mock_runtime.storage.prune_agent_liveness = AsyncMock(return_value=None)

    await list_processes(mock_runtime, {})
    first_task = list_processes_module.handler._prune_task
    assert first_task is not None
    await first_task

    await list_processes(mock_runtime, {})
    second_task = list_processes_module.handler._prune_task

    # Still within the throttle window -- no new prune task scheduled.
    assert second_task is first_task
    mock_runtime.storage.prune_agent_liveness.assert_awaited_once()


async def test_list_processes_reprunes_after_throttle_window(mock_runtime):
    mock_runtime.storage.supports_agent_liveness = True
    mock_runtime.storage.prune_agent_liveness = AsyncMock(return_value=None)

    await list_processes(mock_runtime, {})
    first_task = list_processes_module.handler._prune_task
    await first_task

    # Simulate the throttle window having elapsed.
    list_processes_module.handler._last_prune_attempt_monotonic = (
        time.monotonic() - list_processes_module.handler._PRUNE_THROTTLE_SECONDS - 1
    )

    await list_processes(mock_runtime, {})
    second_task = list_processes_module.handler._prune_task
    assert second_task is not first_task
    await second_task

    assert mock_runtime.storage.prune_agent_liveness.await_count == 2


async def test_list_processes_skips_prune_when_unsupported(mock_runtime):
    mock_runtime.storage.supports_agent_liveness = False
    mock_runtime.storage.prune_agent_liveness = AsyncMock(return_value=None)

    await list_processes(mock_runtime, {})

    mock_runtime.storage.prune_agent_liveness.assert_not_awaited()
    assert list_processes_module.handler._prune_task is None