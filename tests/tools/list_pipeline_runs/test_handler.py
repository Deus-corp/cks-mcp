"""Integration tests for the list_pipeline_runs MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.pipeline.researcher_step import TASK_TYPE as RESEARCH_TASK_TYPE
from cks_mcp.tools.list_pipeline_runs.handler import list_pipeline_runs

pytestmark = pytest.mark.asyncio


class _FakeOutboxTask:
    def __init__(self, task_id, task_type, session_id, payload, last_error=None):
        self.task_id = task_id
        self.task_type = task_type
        self.session_id = session_id
        self.payload = payload
        self.last_error = last_error


class _FakeIdentity:
    def __init__(self, id: str):
        self.id = id


class _FakeObject:
    def __init__(self, id: str, structure: dict):
        self.identity = _FakeIdentity(id)
        self.structure = structure


class _FakeStructure:
    def __init__(self, objects: list[_FakeObject]):
        self.objects = objects


class _FakeSession:
    def __init__(self, objects: list[_FakeObject]):
        self.knowledge_structure = _FakeStructure(objects)


def _obj_with_log(obj_id: str, transition_log: list[dict]) -> _FakeObject:
    return _FakeObject(obj_id, {"transition_log": transition_log, "current_status": "resolved"})


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.list_tasks_by_type = AsyncMock(return_value=[])
    runtime.storage.list_dead_letter_tasks = AsyncMock(return_value=[])
    runtime.get_session = MagicMock(return_value=_FakeSession([]))
    return runtime


async def test_no_session_returns_empty(mock_runtime):
    mock_runtime.get_session = MagicMock(return_value=None)
    result = await list_pipeline_runs(mock_runtime, {"session_id": "missing"})
    assert result == {"runs": [], "count": 0}


async def test_empty_session_no_pipeline_metadata(mock_runtime):
    result = await list_pipeline_runs(mock_runtime, {"session_id": "s1"})
    assert result == {"runs": [], "count": 0}


async def test_run_derived_from_transition_log(mock_runtime):
    run_id = "run-abc"
    obj = _obj_with_log(
        "obj-1",
        [
            {
                "agent": "ResearcherAgent",
                "action": "researched",
                "transitioned_to": "awaiting_review",
                "timestamp": "2026-08-15T00:01:00Z",
                "run_id": run_id,
            },
            {
                "agent": "ReviewerAgent",
                "action": "reviewed",
                "transitioned_to": "resolved",
                "timestamp": "2026-08-15T00:02:00Z",
                "run_id": run_id,
            },
        ],
    )
    mock_runtime.get_session = MagicMock(return_value=_FakeSession([obj]))

    result = await list_pipeline_runs(mock_runtime, {"session_id": "s1"})

    assert result["count"] == 1
    run = result["runs"][0]
    assert run["run_id"] == run_id
    assert run["session_id"] == "s1"
    assert run["object_ids"] == ["obj-1"]
    assert run["status"] == "completed"
    assert run["started_at"] == "2026-08-15T00:01:00Z"
    assert run["updated_at"] == "2026-08-15T00:02:00Z"

    steps_by_name = {s["name"]: s for s in run["steps"]}
    assert steps_by_name["Researcher"]["status"] == "completed"
    assert steps_by_name["Reviewer"]["status"] == "completed"
    assert steps_by_name["Synthesizer"]["status"] == "pending"
    assert steps_by_name["Arbiter"]["status"] == "pending"


async def test_run_still_queued_from_pending_outbox_task(mock_runtime):
    run_id = "run-queued"

    async def _list_tasks_by_type(task_type, session_id=None, drain=True):
        assert drain is False
        if task_type == RESEARCH_TASK_TYPE:
            return [
                _FakeOutboxTask(
                    1, task_type, "s1", {"object_id": "obj-9", "run_id": run_id}
                )
            ]
        return []

    mock_runtime.storage.list_tasks_by_type = AsyncMock(side_effect=_list_tasks_by_type)

    result = await list_pipeline_runs(mock_runtime, {"session_id": "s1"})

    assert result["count"] == 1
    run = result["runs"][0]
    assert run["run_id"] == run_id
    assert run["status"] == "queued"
    assert run["object_ids"] == ["obj-9"]
    steps_by_name = {s["name"]: s for s in run["steps"]}
    assert steps_by_name["Researcher"]["status"] == "pending"


async def test_run_failed_from_dead_letter_task(mock_runtime):
    run_id = "run-failed"

    async def _list_dead_letter_tasks(task_type):
        if task_type == RESEARCH_TASK_TYPE:
            return [
                _FakeOutboxTask(
                    42,
                    task_type,
                    "s1",
                    {"object_id": "obj-5", "run_id": run_id},
                    last_error="LLM provider timeout",
                )
            ]
        return []

    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(side_effect=_list_dead_letter_tasks)

    result = await list_pipeline_runs(mock_runtime, {"session_id": "s1"})

    assert result["count"] == 1
    run = result["runs"][0]
    assert run["status"] == "failed"
    steps_by_name = {s["name"]: s for s in run["steps"]}
    researcher = steps_by_name["Researcher"]
    assert researcher["status"] == "failed"
    assert researcher["error"] == "LLM provider timeout"
    assert researcher["dead_letter_task_id"] == 42


async def test_filters_by_session_id(mock_runtime):
    run_id = "run-other-session"
    obj = _obj_with_log(
        "obj-1",
        [
            {
                "agent": "ResearcherAgent",
                "action": "researched",
                "transitioned_to": "awaiting_review",
                "timestamp": "2026-08-15T00:01:00Z",
                "run_id": run_id,
            }
        ],
    )
    # get_session is already scoped to the requested session_id by the
    # runtime itself; a dead-letter task belonging to a *different*
    # session_id must not leak into this session's runs.
    mock_runtime.get_session = MagicMock(return_value=_FakeSession([obj]))

    async def _list_dead_letter_tasks(task_type):
        if task_type == RESEARCH_TASK_TYPE:
            return [
                _FakeOutboxTask(
                    1, task_type, "other-session", {"object_id": "obj-x", "run_id": "run-x"}
                )
            ]
        return []

    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(side_effect=_list_dead_letter_tasks)

    result = await list_pipeline_runs(mock_runtime, {"session_id": "s1"})

    assert result["count"] == 1
    assert result["runs"][0]["run_id"] == run_id


async def test_applies_limit(mock_runtime):
    objects = []
    for i in range(5):
        objects.append(
            _obj_with_log(
                f"obj-{i}",
                [
                    {
                        "agent": "ResearcherAgent",
                        "action": "researched",
                        "transitioned_to": "awaiting_review",
                        "timestamp": f"2026-08-15T00:0{i}:00Z",
                        "run_id": f"run-{i}",
                    }
                ],
            )
        )
    mock_runtime.get_session = MagicMock(return_value=_FakeSession(objects))

    result = await list_pipeline_runs(mock_runtime, {"session_id": "s1", "limit": 2})

    assert result["count"] == 2
    assert len(result["runs"]) == 2


async def test_run_shape_matches_pipeline_run_contract(mock_runtime):
    run_id = "run-shape"
    obj = _obj_with_log(
        "obj-1",
        [
            {
                "agent": "ResearcherAgent",
                "action": "researched",
                "transitioned_to": "awaiting_review",
                "timestamp": "2026-08-15T00:01:00Z",
                "run_id": run_id,
            }
        ],
    )
    mock_runtime.get_session = MagicMock(return_value=_FakeSession([obj]))

    result = await list_pipeline_runs(mock_runtime, {"session_id": "s1"})
    run = result["runs"][0]

    assert set(run.keys()) == {
        "run_id",
        "session_id",
        "status",
        "started_at",
        "updated_at",
        "object_ids",
        "steps",
    }
    assert run["status"] in ("queued", "running", "completed", "failed")
    for step in run["steps"]:
        assert set(step.keys()) == {
            "name",
            "status",
            "started_at",
            "completed_at",
            "error",
            "dead_letter_task_id",
        }
        assert step["name"] in ("Researcher", "Synthesizer", "Reviewer", "Arbiter")
        assert step["status"] in ("pending", "active", "completed", "failed")


async def test_unsupported_outbox_backend_still_uses_transition_log(mock_runtime):
    mock_runtime.storage.supports_outbox = False
    run_id = "run-inmem"
    obj = _obj_with_log(
        "obj-1",
        [
            {
                "agent": "ResearcherAgent",
                "action": "researched",
                "transitioned_to": "awaiting_review",
                "timestamp": "2026-08-15T00:01:00Z",
                "run_id": run_id,
            }
        ],
    )
    mock_runtime.get_session = MagicMock(return_value=_FakeSession([obj]))

    result = await list_pipeline_runs(mock_runtime, {"session_id": "s1"})

    assert result["count"] == 1
    mock_runtime.storage.list_tasks_by_type.assert_not_awaited()
    mock_runtime.storage.list_dead_letter_tasks.assert_not_awaited()
