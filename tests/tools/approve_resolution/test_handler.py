"""Unit tests for the approve_resolution MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cks_runtime.storage.storage import OutboxTask

from cks_mcp.tools.approve_resolution.handler import approve_resolution

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.list_dead_letter_tasks = AsyncMock(return_value=[])
    return runtime


def _dead_task(task_id=1, task_type="gossip_conflict", session_id="s1"):
    return OutboxTask(
        task_id=task_id,
        task_type=task_type,
        session_id=session_id,
        payload="{}",
        retry_count=1,
    )


async def test_invalid_resolution_shape_rejected(mock_runtime):
    result = await approve_resolution(mock_runtime, {"task_id": 1, "resolution": "nope"})

    assert result["approved"] is False
    assert result["error"] == "invalid_parameter"
    mock_runtime.storage.list_dead_letter_tasks.assert_not_called()


async def test_resolution_missing_tool_or_arguments_rejected(mock_runtime):
    result = await approve_resolution(
        mock_runtime, {"task_id": 1, "resolution": {"tool": "resolve_gossip_conflict"}}
    )

    assert result["approved"] is False
    assert result["error"] == "invalid_parameter"


async def test_unsupported_backend_reports_error(mock_runtime):
    mock_runtime.storage.supports_outbox = False

    result = await approve_resolution(
        mock_runtime,
        {
            "task_id": 1,
            "resolution": {"tool": "resolve_gossip_conflict", "arguments": {}},
        },
    )

    assert result["approved"] is False
    assert result["error"] == "not_supported"


async def test_task_not_found_reports_error(mock_runtime):
    result = await approve_resolution(
        mock_runtime,
        {
            "task_id": 42,
            "resolution": {"tool": "resolve_gossip_conflict", "arguments": {}},
        },
    )

    assert result["approved"] is False
    assert result["error"] == "task_not_dead_lettered"


async def test_tool_task_type_mismatch_rejected(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[_dead_task(task_id=1, task_type="inference_conflict")]
    )

    result = await approve_resolution(
        mock_runtime,
        {
            "task_id": 1,
            # Wrong tool for an inference_conflict task.
            "resolution": {"tool": "resolve_gossip_conflict", "arguments": {}},
        },
    )

    assert result["approved"] is False
    assert result["error"] == "tool_task_type_mismatch"


async def test_unknown_task_type_reports_error(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[_dead_task(task_id=1, task_type="some_new_type")]
    )

    result = await approve_resolution(
        mock_runtime,
        {
            "task_id": 1,
            "resolution": {"tool": "resolve_gossip_conflict", "arguments": {}},
        },
    )

    assert result["approved"] is False
    assert result["error"] == "unknown_task_type"


async def test_successful_resolution_completes_task(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[_dead_task(task_id=1, task_type="gossip_conflict", session_id="s1")]
    )

    fake_result = {"merged": True}
    mock_resolver = AsyncMock(return_value=fake_result)
    with (
        patch.dict(
            "cks_mcp.tools.approve_resolution.handler._RESOLUTION_HANDLERS",
            {"resolve_gossip_conflict": mock_resolver},
        ),
        patch(
            "cks_mcp.tools.approve_resolution.handler.complete_conflict_task",
            new=AsyncMock(return_value={"completed": True}),
        ) as mock_complete,
    ):
        result = await approve_resolution(
            mock_runtime,
            {
                "task_id": 1,
                "resolution": {
                    "tool": "resolve_gossip_conflict",
                    "arguments": {"target_session_id": "s1", "source_session_id": "s2"},
                },
            },
        )

        mock_resolver.assert_awaited_once_with(
            mock_runtime, {"target_session_id": "s1", "source_session_id": "s2"}
        )
        mock_complete.assert_awaited_once_with(mock_runtime, {"task_id": 1})

    assert result == {
        "approved": True,
        "task_id": 1,
        "resolution_result": fake_result,
    }


async def test_failed_resolution_does_not_complete_task(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[_dead_task(task_id=1, task_type="gossip_conflict", session_id="s1")]
    )

    fake_result = {"merged": False, "conflicts": [{"object_id": "obj-1"}]}
    with (
        patch.dict(
            "cks_mcp.tools.approve_resolution.handler._RESOLUTION_HANDLERS",
            {"resolve_gossip_conflict": AsyncMock(return_value=fake_result)},
        ),
        patch(
            "cks_mcp.tools.approve_resolution.handler.complete_conflict_task",
            new=AsyncMock(),
        ) as mock_complete,
    ):
        result = await approve_resolution(
            mock_runtime,
            {
                "task_id": 1,
                "resolution": {
                    "tool": "resolve_gossip_conflict",
                    "arguments": {"target_session_id": "s1", "source_session_id": "s2"},
                },
            },
        )

        mock_complete.assert_not_called()

    assert result["approved"] is False
    assert result["resolution_result"] == fake_result


async def test_resolution_with_error_key_does_not_complete_task(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[_dead_task(task_id=2, task_type="temporal_conflict", session_id="s1")]
    )

    fake_result = {"error": "session_not_found", "message": "Session 's1' not found."}
    with (
        patch.dict(
            "cks_mcp.tools.approve_resolution.handler._RESOLUTION_HANDLERS",
            {"resolve_temporal_conflict": AsyncMock(return_value=fake_result)},
        ),
        patch(
            "cks_mcp.tools.approve_resolution.handler.complete_conflict_task",
            new=AsyncMock(),
        ) as mock_complete,
    ):
        result = await approve_resolution(
            mock_runtime,
            {
                "task_id": 2,
                "resolution": {
                    "tool": "resolve_temporal_conflict",
                    "arguments": {"session_id": "s1", "object_id": "obj-1"},
                },
            },
        )

        mock_complete.assert_not_called()

    assert result["approved"] is False


async def test_commit_result_error_does_not_complete_task(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[_dead_task(task_id=3, task_type="provenance_conflict", session_id="s1")]
    )

    fake_result = {
        "new_record": {"identity": {"id": "rec-2"}},
        "commit_result": {"error": "validation_failed", "message": "bad structure"},
    }
    with (
        patch.dict(
            "cks_mcp.tools.approve_resolution.handler._RESOLUTION_HANDLERS",
            {"refresh_verification": AsyncMock(return_value=fake_result)},
        ),
        patch(
            "cks_mcp.tools.approve_resolution.handler.complete_conflict_task",
            new=AsyncMock(),
        ) as mock_complete,
    ):
        result = await approve_resolution(
            mock_runtime,
            {
                "task_id": 3,
                "resolution": {
                    "tool": "refresh_verification",
                    "arguments": {
                        "session_id": "s1",
                        "record_id": "rec-1",
                        "subject_id": "doc-1",
                        "source_url": "https://example.com",
                    },
                },
            },
        )

        mock_complete.assert_not_called()

    assert result["approved"] is False
