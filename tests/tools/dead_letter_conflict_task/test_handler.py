"""Unit tests for the dead_letter_conflict_task MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.dead_letter_conflict_task.handler import dead_letter_conflict_task

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.dead_letter_outbox_task = AsyncMock(return_value=None)
    return runtime


async def test_unsupported_backend_reports_unsupported(mock_runtime):
    mock_runtime.storage.supports_outbox = False

    result = await dead_letter_conflict_task(mock_runtime, {"task_id": 1, "error": "boom"})

    assert result == {"dead_lettered": False, "supported": False}
    mock_runtime.storage.dead_letter_outbox_task.assert_not_called()


async def test_dead_letters_task(mock_runtime):
    result = await dead_letter_conflict_task(
        mock_runtime, {"task_id": 9, "error": "no confident resolution after 3 attempts"}
    )

    assert result == {"dead_lettered": True, "supported": True, "task_id": 9}
    mock_runtime.storage.dead_letter_outbox_task.assert_awaited_once_with(
        9, "no confident resolution after 3 attempts"
    )
