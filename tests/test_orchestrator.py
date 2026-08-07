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
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step])

    result = await orchestrator.run_sequential()

    assert result.total_processed == 1
    assert len(step.calls) == 1
    mock_runtime.storage.complete_outbox_task.assert_awaited_once_with(1)


async def test_run_sequential_fails_and_retries(mock_runtime):
    import json

    task = _FakeTask(2, "pipeline_review_request", "s1", json.dumps({"object_id": "o1"}), retry_count=0)
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=[task, None])

    step = _StubStep("ReviewerAgent", "awaiting_review", "pipeline_review_request", Resolution(False, "boom"))
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step], max_retries=5)

    await orchestrator.run_sequential()

    mock_runtime.storage.fail_outbox_task.assert_awaited_once()
    mock_runtime.storage.dead_letter_outbox_task.assert_not_awaited()


async def test_run_sequential_dead_letters_after_max_retries(mock_runtime):
    import json

    task = _FakeTask(3, "pipeline_review_request", "s1", json.dumps({"object_id": "o1"}), retry_count=4)
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=[task, None])

    step = _StubStep("ReviewerAgent", "awaiting_review", "pipeline_review_request", Resolution(False, "boom"))
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step], max_retries=5)

    await orchestrator.run_sequential()

    mock_runtime.storage.dead_letter_outbox_task.assert_awaited_once()
    mock_runtime.storage.fail_outbox_task.assert_not_awaited()


async def test_run_sequential_publishes_started_and_completed_events(mock_runtime):
    import json

    task = _FakeTask(4, "pipeline_research_request", "s1", json.dumps({"object_id": "o1"}))
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=[task, None])

    step = _StubStep("ResearcherAgent", "awaiting_research", "pipeline_research_request", Resolution(True, "awaiting_review"))
    bus = EventBus()
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step], event_bus=bus)

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
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step])

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
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step1, step2])

    result = await orchestrator.run_concurrent()

    assert result.total_processed == 2
    assert len(step1.calls) == 1
    assert len(step2.calls) == 1


async def test_lease_lost_is_counted_as_abandoned_not_processed(mock_runtime):
    import asyncio
    import json

    task = _FakeTask(7, "pipeline_research_request", "s1", json.dumps({"object_id": "o1"}))
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=[task, None])
    mock_runtime.storage.touch_outbox_task = AsyncMock(return_value=False)

    class _SlowStep(_StubStep):
        async def run(self, ctx, task):
            # Yield control so the heartbeat task actually gets a tick
            # in before this resolver returns -- a resolver with no
            # internal await point never gives asyncio.create_task's
            # heartbeat coroutine a chance to run before it's cancelled.
            await asyncio.sleep(0.02)
            return await super().run(ctx, task)

    step = _SlowStep("ResearcherAgent", "awaiting_research", "pipeline_research_request", Resolution(True, "awaiting_review"))
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step], heartbeat_interval=0.005)

    result = await orchestrator.run_sequential()

    assert result.steps[0].processed == 0
    assert result.steps[0].abandoned == 1
    mock_runtime.storage.complete_outbox_task.assert_not_awaited()
    mock_runtime.storage.fail_outbox_task.assert_not_awaited()
    mock_runtime.storage.dead_letter_outbox_task.assert_not_awaited()


async def test_run_concurrent_isolates_one_steps_infra_failure_from_the_other(mock_runtime):
    """
    Regression test: an infrastructure failure in one step's drain loop
    (claim/complete/fail/dead-letter/event-bus raising, as opposed to
    an individual task's resolver failing normally) must not crash
    ``asyncio.gather`` and must not prevent the other step's drain from
    completing its own work.
    """
    import json

    task2 = _FakeTask(9, "pipeline_review_request", "s1", json.dumps({"object_id": "o2"}))

    async def _dequeue(task_type):
        if task_type == "pipeline_research_request":
            raise ConnectionError("storage backend unreachable")
        if task_type == "pipeline_review_request" and not getattr(_dequeue, "_done", False):
            _dequeue._done = True
            return task2
        return None

    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=_dequeue)

    step1 = _StubStep("ResearcherAgent", "awaiting_research", "pipeline_research_request", Resolution(True, "awaiting_review"))
    step2 = _StubStep("ReviewerAgent", "awaiting_review", "pipeline_review_request", Resolution(True, "resolved"))
    orchestrator = CKSAgentOrchestrator(mock_runtime, [step1, step2])

    result = await orchestrator.run_concurrent()

    by_name = {s.step_name: s for s in result.steps}
    assert by_name["ResearcherAgent"].error is not None
    assert by_name["ResearcherAgent"].processed == 0
    assert len(step1.calls) == 0

    # The Reviewer's own drain must have completed normally despite
    # the Researcher's drain having blown up.
    assert by_name["ReviewerAgent"].error is None
    assert by_name["ReviewerAgent"].processed == 1
    assert len(step2.calls) == 1