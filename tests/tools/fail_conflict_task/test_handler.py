"""Unit tests for the fail_conflict_task MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.fail_conflict_task.handler import fail_conflict_task

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.fail_outbox_task = AsyncMock(return_value=None)
    return runtime


async def test_unsupported_backend_reports_unsupported(mock_runtime):
    mock_runtime.storage.supports_outbox = False

    result = await fail_conflict_task(
        mock_runtime, {"task_id": 1, "retry_count": 1, "error": "boom"}
    )

    assert result == {"failed": False, "supported": False}
    mock_runtime.storage.fail_outbox_task.assert_not_called()


async def test_reschedules_with_backoff(mock_runtime):
    result = await fail_conflict_task(
        mock_runtime, {"task_id": 5, "retry_count": 2, "error": "transient LLM timeout"}
    )

    assert result["failed"] is True
    assert result["supported"] is True
    assert result["task_id"] == 5
    assert result["retry_count"] == 2
    assert "next_retry_at" in result

    mock_runtime.storage.fail_outbox_task.assert_awaited_once()
    call_args = mock_runtime.storage.fail_outbox_task.await_args.args
    assert call_args[0] == 5
    assert call_args[1] == 2
    assert call_args[2] == "transient LLM timeout"


async def test_backoff_is_capped_at_one_hour(mock_runtime):
    """A very high retry_count must not schedule a multi-day delay --
    same cap OutboxEmbeddingWorker applies to projection tasks."""
    import datetime

    before = datetime.datetime.now(datetime.UTC)
    result = await fail_conflict_task(
        mock_runtime, {"task_id": 1, "retry_count": 20, "error": "boom"}
    )
    next_retry_at = datetime.datetime.fromisoformat(result["next_retry_at"])

    assert (next_retry_at - before).total_seconds() <= 3601
