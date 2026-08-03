"""Unit tests for the complete_conflict_task MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.complete_conflict_task.handler import complete_conflict_task

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.complete_outbox_task = AsyncMock(return_value=None)
    return runtime


async def test_unsupported_backend_reports_unsupported(mock_runtime):
    mock_runtime.storage.supports_outbox = False

    result = await complete_conflict_task(mock_runtime, {"task_id": 1})

    assert result == {"completed": False, "supported": False}
    mock_runtime.storage.complete_outbox_task.assert_not_called()


async def test_completes_task(mock_runtime):
    result = await complete_conflict_task(mock_runtime, {"task_id": 42})

    assert result == {"completed": True, "supported": True, "task_id": 42}
    mock_runtime.storage.complete_outbox_task.assert_awaited_once_with(42)
