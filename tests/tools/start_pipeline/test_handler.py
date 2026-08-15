"""Unit tests for the start_pipeline MCP tool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.orchestrator import pipeline_run_hash
from cks_mcp.pipeline.researcher_step import TASK_TYPE as RESEARCH_TASK_TYPE
from cks_mcp.tools.start_pipeline.handler import start_pipeline

pytestmark = pytest.mark.asyncio


class _FakeIdentity:
    def __init__(self, id: str):
        self.id = id


class _FakeObject:
    def __init__(self, id: str):
        self.identity = _FakeIdentity(id)


class _FakeStructure:
    def __init__(self, object_ids: list[str]):
        self.objects = [_FakeObject(oid) for oid in object_ids]


class _FakeSession:
    def __init__(self, object_ids: list[str]):
        self.knowledge_structure = _FakeStructure(object_ids)


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.enqueue_task = AsyncMock()
    runtime.get_session = MagicMock(return_value=_FakeSession(["obj-1", "obj-2", "obj-3"]))
    return runtime


async def test_missing_session_id(mock_runtime):
    result = await start_pipeline(mock_runtime, {})
    assert result.get("error") == "missing_parameter"


async def test_invalid_mode(mock_runtime):
    result = await start_pipeline(
        mock_runtime, {"session_id": "s1", "mode": "parallel-ish"}
    )
    assert result.get("error") == "invalid_parameter"


async def test_missing_session(mock_runtime):
    mock_runtime.get_session = MagicMock(return_value=None)
    result = await start_pipeline(mock_runtime, {"session_id": "does-not-exist"})
    assert result.get("error") == "internal_error"
    assert "does-not-exist" in result["message"]


async def test_unsupported_backend(mock_runtime):
    mock_runtime.storage.supports_outbox = False
    result = await start_pipeline(mock_runtime, {"session_id": "s1"})
    assert result["status"] == "unsupported"
    assert result["supported"] is False
    mock_runtime.storage.enqueue_task.assert_not_awaited()


async def test_explicit_object_ids(mock_runtime):
    result = await start_pipeline(
        mock_runtime, {"session_id": "s1", "object_ids": ["obj-2"]}
    )
    assert result["status"] == "started"
    assert result["mode"] == "sequential"
    assert result["enqueued_objects"] == ["obj-2"]
    assert result["run_id"] == pipeline_run_hash("s1", ["obj-2"], "v1")

    mock_runtime.storage.enqueue_task.assert_awaited_once()
    kwargs = mock_runtime.storage.enqueue_task.await_args.kwargs
    assert kwargs["task_type"] == RESEARCH_TASK_TYPE
    assert kwargs["session_id"] == "s1"
    assert json.loads(kwargs["payload"]) == {"object_id": "obj-2", "run_id": result["run_id"]}


async def test_all_objects_when_object_ids_omitted(mock_runtime):
    result = await start_pipeline(mock_runtime, {"session_id": "s1", "mode": "concurrent"})
    assert result["status"] == "started"
    assert result["mode"] == "concurrent"
    assert result["enqueued_objects"] == ["obj-1", "obj-2", "obj-3"]
    assert mock_runtime.storage.enqueue_task.await_count == 3
    enqueued_ids = {
        json.loads(call.kwargs["payload"])["object_id"]
        for call in mock_runtime.storage.enqueue_task.await_args_list
    }
    assert enqueued_ids == {"obj-1", "obj-2", "obj-3"}
    enqueued_run_ids = {
        json.loads(call.kwargs["payload"])["run_id"]
        for call in mock_runtime.storage.enqueue_task.await_args_list
    }
    assert enqueued_run_ids == {result["run_id"]}


async def test_no_objects_in_session(mock_runtime):
    mock_runtime.get_session = MagicMock(return_value=_FakeSession([]))
    result = await start_pipeline(mock_runtime, {"session_id": "empty-session"})
    assert result["status"] == "no_objects"
    assert result["enqueued_objects"] == []
    mock_runtime.storage.enqueue_task.assert_not_awaited()


async def test_sandbox_isolation_forks_and_enqueues_against_sandbox(mock_runtime, monkeypatch):
    fake_fork = AsyncMock(
        return_value={"sandbox_session_id": "sandbox-abc", "parent_session_id": "parent-1"}
    )
    monkeypatch.setattr("cks_mcp.tools.start_pipeline.handler.fork_sandbox", fake_fork)

    result = await start_pipeline(
        mock_runtime,
        {
            "session_id": "parent-1",
            "object_ids": ["obj-9"],
            "parent_session_id": "parent-1",
        },
    )

    fake_fork.assert_awaited_once_with(mock_runtime, {"session_id": "parent-1"})
    assert result["status"] == "started"
    assert result["session_id"] == "sandbox-abc"
    assert result["sandbox_session_id"] == "sandbox-abc"
    assert result["parent_session_id"] == "parent-1"

    kwargs = mock_runtime.storage.enqueue_task.await_args.kwargs
    assert kwargs["session_id"] == "sandbox-abc"


async def test_sandbox_fork_failure_is_reported(mock_runtime, monkeypatch):
    fake_fork = AsyncMock(return_value={"error": "branch_failed", "message": "boom"})
    monkeypatch.setattr("cks_mcp.tools.start_pipeline.handler.fork_sandbox", fake_fork)

    result = await start_pipeline(
        mock_runtime,
        {"session_id": "parent-1", "parent_session_id": "parent-1"},
    )

    assert result.get("error") == "internal_error"
    mock_runtime.storage.enqueue_task.assert_not_awaited()
