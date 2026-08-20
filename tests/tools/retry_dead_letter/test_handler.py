"""Unit tests for the retry_dead_letter MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.retry_dead_letter.handler import retry_dead_letter

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.retry_dead_letter_task = AsyncMock(return_value=True)
    return runtime


async def test_unsupported_backend_reports_unsupported(mock_runtime):
    mock_runtime.storage.supports_outbox = False

    result = await retry_dead_letter(mock_runtime, {"task_id": 1})

    assert result == {
        "retried": False,
        "error": "not_supported",
        "message": (
            "This storage backend does not support the persistent outbox "
            "(e.g. the default InMemoryStorage) -- there is no dead-letter "
            "queue to retry."
        ),
    }
    mock_runtime.storage.retry_dead_letter_task.assert_not_called()


async def test_retries_dead_lettered_task(mock_runtime):
    result = await retry_dead_letter(mock_runtime, {"task_id": 9})

    assert result == {"retried": True, "task_id": 9}
    mock_runtime.storage.retry_dead_letter_task.assert_awaited_once_with(9)


async def test_task_not_found_or_not_dead_returns_error(mock_runtime):
    mock_runtime.storage.retry_dead_letter_task = AsyncMock(return_value=False)

    result = await retry_dead_letter(mock_runtime, {"task_id": 42})

    assert result == {
        "retried": False,
        "task_id": 42,
        "error": "task_not_found",
        "message": (
            "Task 42 was not found among DEAD-lettered tasks -- "
            "it may not exist, or it may not currently be in the DEAD "
            "state (see list_dead_lettered_conflicts for the current set)."
        ),
    }
    mock_runtime.storage.retry_dead_letter_task.assert_awaited_once_with(42)