"""Unit tests for the list_dead_lettered_conflicts MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from cks_runtime.storage.storage import OutboxTask

from cks_mcp.tools.list_dead_lettered_conflicts.handler import (
    list_dead_lettered_conflicts,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.list_dead_letter_tasks = AsyncMock(return_value=[])
    return runtime


async def test_unsupported_backend_reports_unsupported(mock_runtime):
    mock_runtime.storage.supports_outbox = False

    result = await list_dead_lettered_conflicts(mock_runtime, {})

    assert result == {"tasks": [], "count": 0, "supported": False}
    mock_runtime.storage.list_dead_letter_tasks.assert_not_called()


async def test_empty_returns_empty_list(mock_runtime):
    result = await list_dead_lettered_conflicts(mock_runtime, {})

    assert result == {"tasks": [], "count": 0, "supported": True}
    mock_runtime.storage.list_dead_letter_tasks.assert_awaited_once_with(task_type=None)


async def test_returns_and_parses_dead_lettered_tasks(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=3,
                task_type="inference_conflict",
                session_id="s1",
                payload='{"version_id": "v1"}',
                retry_count=5,
            )
        ]
    )

    result = await list_dead_lettered_conflicts(mock_runtime, {"task_type": "inference_conflict"})

    assert result["count"] == 1
    assert result["tasks"][0]["task_id"] == 3
    assert result["tasks"][0]["payload"] == {"version_id": "v1"}
    mock_runtime.storage.list_dead_letter_tasks.assert_awaited_once_with(
        task_type="inference_conflict"
    )
