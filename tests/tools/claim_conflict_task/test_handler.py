"""Unit tests for the claim_conflict_task MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from cks_runtime.storage.storage import OutboxTask

from cks_mcp.tools.claim_conflict_task.handler import claim_conflict_task

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.dequeue_next_outbox_task = AsyncMock(return_value=None)
    return runtime


async def test_unsupported_backend_reports_unsupported(mock_runtime):
    mock_runtime.storage.supports_outbox = False

    result = await claim_conflict_task(mock_runtime, {"task_type": "gossip_conflict"})

    assert result["task"] is None
    assert result["supported"] is False
    mock_runtime.storage.dequeue_next_outbox_task.assert_not_called()


async def test_no_eligible_task_returns_none(mock_runtime):
    result = await claim_conflict_task(mock_runtime, {"task_type": "gossip_conflict"})

    assert result == {"task": None, "supported": True}
    mock_runtime.storage.dequeue_next_outbox_task.assert_awaited_once_with(
        task_type="gossip_conflict"
    )


async def test_claims_and_parses_json_payload(mock_runtime):
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(
        return_value=OutboxTask(
            task_id=7,
            task_type="gossip_conflict",
            session_id="s1",
            payload='{"source_replica_id": "r1", "conflicts": ["obj-1"]}',
            retry_count=0,
        )
    )

    result = await claim_conflict_task(mock_runtime, {"task_type": "gossip_conflict"})

    assert result["supported"] is True
    assert result["task"]["task_id"] == 7
    assert result["task"]["task_type"] == "gossip_conflict"
    assert result["task"]["session_id"] == "s1"
    assert result["task"]["payload"] == {"source_replica_id": "r1", "conflicts": ["obj-1"]}
    assert result["task"]["retry_count"] == 0


async def test_non_json_payload_passed_through_raw(mock_runtime):
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(
        return_value=OutboxTask(
            task_id=1, task_type="gossip_conflict", session_id="s1",
            payload="not json", retry_count=0,
        )
    )

    result = await claim_conflict_task(mock_runtime, {"task_type": "gossip_conflict"})

    assert result["task"]["payload"] == "not json"
