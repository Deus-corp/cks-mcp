"""Unit tests for the reject_resolution MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from cks_runtime.storage.storage import OutboxTask

from cks_mcp.tools.reject_resolution.handler import reject_resolution

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.list_dead_letter_tasks = AsyncMock(return_value=[])
    runtime.storage.dead_letter_outbox_task = AsyncMock(return_value=None)
    return runtime


async def test_unsupported_backend_reports_error(mock_runtime):
    mock_runtime.storage.supports_outbox = False

    result = await reject_resolution(mock_runtime, {"task_id": 1})

    assert result == {
        "rejected": False,
        "task_id": 1,
        "error": "not_supported",
        "message": (
            "This storage backend does not support the persistent outbox "
            "(e.g. the default InMemoryStorage) -- there is no dead-letter "
            "queue to reject against."
        ),
    }
    mock_runtime.storage.dead_letter_outbox_task.assert_not_called()


async def test_task_not_found_reports_error(mock_runtime):
    result = await reject_resolution(mock_runtime, {"task_id": 999})

    assert result["rejected"] is False
    assert result["error"] == "task_not_dead_lettered"
    mock_runtime.storage.dead_letter_outbox_task.assert_not_called()


async def test_rejects_with_reason(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=5,
                task_type="gossip_conflict",
                session_id="s1",
                payload="{}",
                retry_count=2,
            )
        ]
    )

    result = await reject_resolution(
        mock_runtime,
        {"task_id": 5, "reason": "wrong relation would be removed"},
    )

    assert result == {
        "rejected": True,
        "task_id": 5,
        "reason": "wrong relation would be removed",
    }
    mock_runtime.storage.dead_letter_outbox_task.assert_awaited_once_with(
        5, "Rejected by human: wrong relation would be removed"
    )


async def test_rejects_without_reason(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=6,
                task_type="temporal_conflict",
                session_id="s1",
                payload="{}",
                retry_count=0,
            )
        ]
    )

    result = await reject_resolution(mock_runtime, {"task_id": 6})

    assert result == {"rejected": True, "task_id": 6, "reason": None}
    mock_runtime.storage.dead_letter_outbox_task.assert_awaited_once_with(
        6, "Rejected by human."
    )


async def test_reject_leaves_task_dead_not_removed(mock_runtime):
    """reject_resolution must never call complete_outbox_task -- the task
    stays in the DEAD state, only annotated."""
    mock_runtime.storage.complete_outbox_task = AsyncMock()
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=7,
                task_type="contradiction_detected",
                session_id="s1",
                payload="{}",
                retry_count=0,
            )
        ]
    )

    await reject_resolution(mock_runtime, {"task_id": 7, "reason": "keep as is"})

    mock_runtime.storage.complete_outbox_task.assert_not_called()
