"""Unit tests for cks_mcp.orchestrator.CKSAgentOrchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from cks_runtime.events.event_bus import EventBus
from cks_runtime.events.runtime_event import AgentStepCompleted, AgentStepStarted

from cks_mcp.agent_loop import Resolution
from cks_mcp.orchestrator import CKSAgentOrchestrator

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.dequeue_next_outbox_task = AsyncMock(return_value=None)
    runtime.storage.complete_outbox_task = AsyncMock()
    runtime.storage.fail_outbox_task = AsyncMock()
    runtime.storage.dead_letter_outbox_task = AsyncMock()
    runtime.storage.touch_outbox_task = AsyncMock(return_value=True)
    runtime.events = EventBus()
    return runtime


class _FakeTask:
    def __init__(self, task_id, task_type, session_id, payload, retry_count=0):
        self.task_id = task_id
        self.task_type = task_type
        self.session_id = session_id
        self.payload = payload
        self.retry_count = retry_count


class _StubStep:
    def __init__(self, name, claims_status, task_type, resolution):
        self.name = name
        self.claims_status = claims_status
        self.task_type = task_type
        self._resolution = resolution
        self.calls: list[dict] = []

    async def run(self, ctx, task):
        self.calls.append(task)
        return self._resolution


async def test_run_sequential_drains_each_step_and_completes(mock_runtime):
    import json

    task = _FakeTask(1, "pipeline_research_request", "s1", json.dumps({"object_id": "o1"}))
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=[task, None])

    step = _StubStep("ResearcherAgent", "awaiting_research", "pipeline_research_request", Resolution(True, "awaiting_review"))
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step], session_id="s1")

    result = await orchestrator.run_sequential()

    assert result.total_processed == 1
    assert len(step.calls) == 1
    mock_runtime.storage.complete_outbox_task.assert_awaited_once_with(1)


async def test_run_sequential_fails_and_retries(mock_runtime):
    import json

    task = _FakeTask(2, "pipeline_review_request", "s1", json.dumps({"object_id": "o1"}), retry_count=0)
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=[task, None])

    step = _StubStep("ReviewerAgent", "awaiting_review", "pipeline_review_request", Resolution(False, "boom"))
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step], session_id="s1", max_retries=5)

    await orchestrator.run_sequential()

    mock_runtime.storage.fail_outbox_task.assert_awaited_once()
    mock_runtime.storage.dead_letter_outbox_task.assert_not_awaited()


async def test_run_sequential_dead_letters_after_max_retries(mock_runtime):
    import json

    task = _FakeTask(3, "pipeline_review_request", "s1", json.dumps({"object_id": "o1"}), retry_count=4)
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=[task, None])

    step = _StubStep("ReviewerAgent", "awaiting_review", "pipeline_review_request", Resolution(False, "boom"))
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step], session_id="s1", max_retries=5)

    await orchestrator.run_sequential()

    mock_runtime.storage.dead_letter_outbox_task.assert_awaited_once()
    mock_runtime.storage.fail_outbox_task.assert_not_awaited()


async def test_run_sequential_publishes_started_and_completed_events(mock_runtime):
    import json

    task = _FakeTask(4, "pipeline_research_request", "s1", json.dumps({"object_id": "o1"}))
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=[task, None])

    step = _StubStep("ResearcherAgent", "awaiting_research", "pipeline_research_request", Resolution(True, "awaiting_review"))
    bus = EventBus()
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step], session_id="s1", event_bus=bus)

    await orchestrator.run_sequential()

    started = [e for e in bus.history() if isinstance(e, AgentStepStarted)]
    completed = [e for e in bus.history() if isinstance(e, AgentStepCompleted)]
    assert len(started) == 1
    assert started[0].step_name == "ResearcherAgent"
    assert started[0].object_id == "o1"
    assert len(completed) == 1
    assert completed[0].succeeded is True
    assert completed[0].transitioned_to == "awaiting_review"


async def test_run_sequential_unsupported_storage_returns_zero(mock_runtime):
    mock_runtime.storage.supports_outbox = False
    step = _StubStep("ResearcherAgent", "awaiting_research", "pipeline_research_request", Resolution(True, ""))
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step], session_id="s1")

    result = await orchestrator.run_sequential()

    assert result.total_processed == 0
    assert step.calls == []


async def test_run_concurrent_runs_independent_steps(mock_runtime):
    import json

    task1 = _FakeTask(5, "pipeline_research_request", "s1", json.dumps({"object_id": "o1"}))
    task2 = _FakeTask(6, "pipeline_review_request", "s1", json.dumps({"object_id": "o2"}))

    # Each queue should only yield its own task once, then report empty --
    # keyed off task_type since concurrent-drain call ordering under
    # asyncio.gather is not guaranteed.
    seen = set()

    async def _dequeue_once(task_type):
        if task_type in seen:
            return None
        seen.add(task_type)
        return task1 if task_type == "pipeline_research_request" else task2

    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=_dequeue_once)

    step1 = _StubStep("ResearcherAgent", "awaiting_research", "pipeline_research_request", Resolution(True, "awaiting_review"))
    step2 = _StubStep("ReviewerAgent", "awaiting_review", "pipeline_review_request", Resolution(True, "resolved"))
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step1, step2], session_id="s1")

    result = await orchestrator.run_concurrent()

    assert result.total_processed == 2
    assert len(step1.calls) == 1
    assert len(step2.calls) == 1