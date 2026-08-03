"""Unit tests for cks_mcp.critic_agent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from cks_runtime.storage.storage import OutboxTask

from cks_mcp.critic_agent import (
    CriticAgentSettings,
    Resolution,
    _process_one,
    resolve_gossip_conflict,
    resolve_inference_conflict,
    run_once,
)

pytestmark = pytest.mark.asyncio


def _settings(**overrides) -> CriticAgentSettings:
    base = CriticAgentSettings(poll_interval=0.01, max_retries=3, storage_path=":memory:")
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.dequeue_next_outbox_task = AsyncMock(return_value=None)
    runtime.storage.complete_outbox_task = AsyncMock()
    runtime.storage.fail_outbox_task = AsyncMock()
    runtime.storage.dead_letter_outbox_task = AsyncMock()
    return runtime


# ---------------------------------------------------------------------------
# resolve_gossip_conflict
# ---------------------------------------------------------------------------


async def test_gossip_conflict_missing_source_session_id(mock_runtime):
    task = {"session_id": "s1", "payload": {}}
    resolution = await resolve_gossip_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "source_session_id" in resolution.detail


async def test_gossip_conflict_non_dict_payload(mock_runtime):
    task = {"session_id": "s1", "payload": "not a dict"}
    resolution = await resolve_gossip_conflict(mock_runtime, task)
    assert resolution.resolved is False


async def test_gossip_conflict_merges_cleanly(mock_runtime, monkeypatch):
    task = {"session_id": "target", "payload": {"source_session_id": "source"}}

    async def _fake_merge_branch(runtime, arguments):
        assert arguments == {
            "target_session_id": "target",
            "source_session_id": "source",
        }
        return {"merged": True, "serialized": {}}

    monkeypatch.setattr("cks_mcp.critic_agent.merge_branch", _fake_merge_branch)

    resolution = await resolve_gossip_conflict(mock_runtime, task)
    assert resolution.resolved is True


async def test_gossip_conflict_structural_conflict_not_auto_resolved(mock_runtime, monkeypatch):
    task = {"session_id": "target", "payload": {"source_session_id": "source"}}

    async def _fake_merge_branch(runtime, arguments):
        return {"merged": False, "conflicts": [{"object_id": "obj-1"}]}

    monkeypatch.setattr("cks_mcp.critic_agent.merge_branch", _fake_merge_branch)

    resolution = await resolve_gossip_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "1 structural conflict" in resolution.detail


# ---------------------------------------------------------------------------
# resolve_inference_conflict
# ---------------------------------------------------------------------------


async def test_inference_conflict_no_arbitrable_diagnostics(mock_runtime):
    task = {
        "session_id": "s1",
        "payload": {
            "diagnostics": [
                {"code": "CKS-EXT-STALE-PREMISE", "location": "obj-1"},
            ]
        },
    }
    resolution = await resolve_inference_conflict(mock_runtime, task)
    assert resolution.resolved is True


async def test_inference_conflict_auto_resolves_and_commits(mock_runtime, monkeypatch):
    task = {
        "session_id": "s1",
        "payload": {
            "diagnostics": [
                {"code": "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT", "location": "obj-1"},
            ]
        },
    }

    async def _fake_arbitrate(runtime, arguments):
        assert arguments["session_id"] == "s1"
        assert arguments["conclusion_ids"] == ["obj-1"]
        assert arguments["auto_resolve"] is True
        assert arguments["commit"] is True
        return {
            "session_id": "s1",
            "results": [
                {"conclusion_id": "obj-1", "conflict": True, "decision": {"winner_step_id": "x"}}
            ],
            "commit_result": {"committed": True},
        }

    monkeypatch.setattr(
        "cks_mcp.critic_agent.arbitrate_inference_conflict", _fake_arbitrate
    )

    resolution = await resolve_inference_conflict(mock_runtime, task)
    assert resolution.resolved is True


async def test_inference_conflict_leaves_unresolved_conclusions(mock_runtime, monkeypatch):
    task = {
        "session_id": "s1",
        "payload": {
            "diagnostics": [
                {"code": "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT", "location": "obj-1"},
            ]
        },
    }

    async def _fake_arbitrate(runtime, arguments):
        return {
            "session_id": "s1",
            "results": [{"conclusion_id": "obj-1", "conflict": True}],
        }

    monkeypatch.setattr(
        "cks_mcp.critic_agent.arbitrate_inference_conflict", _fake_arbitrate
    )

    resolution = await resolve_inference_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "obj-1" in resolution.detail


async def test_inference_conflict_nothing_to_commit_is_resolved(mock_runtime, monkeypatch):
    """A conflict that already cleared itself (conflict: False) needs no commit."""
    task = {
        "session_id": "s1",
        "payload": {
            "diagnostics": [
                {"code": "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT", "location": "obj-1"},
            ]
        },
    }

    async def _fake_arbitrate(runtime, arguments):
        return {
            "session_id": "s1",
            "results": [{"conclusion_id": "obj-1", "conflict": False}],
        }

    monkeypatch.setattr(
        "cks_mcp.critic_agent.arbitrate_inference_conflict", _fake_arbitrate
    )

    resolution = await resolve_inference_conflict(mock_runtime, task)
    assert resolution.resolved is True


# ---------------------------------------------------------------------------
# _process_one / run_once: claim -> resolve -> complete/fail/dead-letter
# ---------------------------------------------------------------------------


async def test_process_one_unsupported_backend_returns_none(mock_runtime):
    mock_runtime.storage.supports_outbox = False
    result = await _process_one(mock_runtime, "gossip_conflict", _settings())
    assert result is None


async def test_process_one_empty_queue_returns_none(mock_runtime):
    result = await _process_one(mock_runtime, "gossip_conflict", _settings())
    assert result is None


async def test_process_one_completes_on_success(mock_runtime, monkeypatch):
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(
        return_value=OutboxTask(
            task_id=1,
            task_type="gossip_conflict",
            session_id="s1",
            payload='{"source_session_id": "src"}',
            retry_count=0,
        )
    )

    async def _fake_resolver(runtime, task):
        return Resolution(True)

    monkeypatch.setitem(
        __import__("cks_mcp.critic_agent", fromlist=["_RESOLVERS"])._RESOLVERS,
        "gossip_conflict",
        _fake_resolver,
    )

    result = await _process_one(mock_runtime, "gossip_conflict", _settings())
    assert result is True
    mock_runtime.storage.complete_outbox_task.assert_awaited_once_with(1)
    mock_runtime.storage.fail_outbox_task.assert_not_called()
    mock_runtime.storage.dead_letter_outbox_task.assert_not_called()


async def test_process_one_retries_transient_failure(mock_runtime, monkeypatch):
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(
        return_value=OutboxTask(
            task_id=2,
            task_type="gossip_conflict",
            session_id="s1",
            payload="{}",
            retry_count=0,
        )
    )

    async def _fake_resolver(runtime, task):
        return Resolution(False, "transient boom")

    monkeypatch.setitem(
        __import__("cks_mcp.critic_agent", fromlist=["_RESOLVERS"])._RESOLVERS,
        "gossip_conflict",
        _fake_resolver,
    )

    result = await _process_one(mock_runtime, "gossip_conflict", _settings(max_retries=3))
    assert result is True
    mock_runtime.storage.fail_outbox_task.assert_awaited_once()
    args = mock_runtime.storage.fail_outbox_task.await_args.args
    assert args[0] == 2
    assert args[1] == 1  # retry_count + 1
    mock_runtime.storage.dead_letter_outbox_task.assert_not_called()
    mock_runtime.storage.complete_outbox_task.assert_not_called()


async def test_process_one_dead_letters_after_max_retries(mock_runtime, monkeypatch):
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(
        return_value=OutboxTask(
            task_id=3,
            task_type="gossip_conflict",
            session_id="s1",
            payload="{}",
            retry_count=2,  # next attempt (3) will hit max_retries=3
        )
    )

    async def _fake_resolver(runtime, task):
        return Resolution(False, "still failing")

    monkeypatch.setitem(
        __import__("cks_mcp.critic_agent", fromlist=["_RESOLVERS"])._RESOLVERS,
        "gossip_conflict",
        _fake_resolver,
    )

    result = await _process_one(mock_runtime, "gossip_conflict", _settings(max_retries=3))
    assert result is True
    mock_runtime.storage.dead_letter_outbox_task.assert_awaited_once_with(3, "still failing")
    mock_runtime.storage.fail_outbox_task.assert_not_called()
    mock_runtime.storage.complete_outbox_task.assert_not_called()


async def test_process_one_survives_resolver_exception(mock_runtime, monkeypatch):
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(
        return_value=OutboxTask(
            task_id=4,
            task_type="gossip_conflict",
            session_id="s1",
            payload="{}",
            retry_count=0,
        )
    )

    async def _raising_resolver(runtime, task):
        raise RuntimeError("boom")

    monkeypatch.setitem(
        __import__("cks_mcp.critic_agent", fromlist=["_RESOLVERS"])._RESOLVERS,
        "gossip_conflict",
        _raising_resolver,
    )

    result = await _process_one(mock_runtime, "gossip_conflict", _settings(max_retries=3))
    assert result is True
    mock_runtime.storage.fail_outbox_task.assert_awaited_once()
    error_arg = mock_runtime.storage.fail_outbox_task.await_args.args[2]
    assert "boom" in error_arg


async def test_end_to_end_gossip_conflict_resolution_with_real_storage(tmp_path):
    """
    No mocks: a real SQLite-backed Runtime, a real enqueued outbox
    task, and a real merge_branch call. Exercises the full claim ->
    resolve -> complete path exactly as it runs in production, the
    highest-risk part of this module (the mocked tests above already
    cover the branching logic in isolation).
    """
    import json

    from cks_runtime.config import RuntimeConfig
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter

    from cks_mcp.tools.branch.handler import create_branch
    from cks_mcp.tools.evolve.handler import evolve_knowledge

    db_path = str(tmp_path / "critic_agent_test.db")
    runtime = await Runtime.create(
        core=CksCoreAdapter(), config=RuntimeConfig(storage_path=db_path)
    )
    if hasattr(runtime, '_outbox_worker') and runtime._outbox_worker is not None:
        await runtime._outbox_worker.stop()
    if hasattr(runtime, '_inference_sweeper') and runtime._inference_sweeper is not None:
        await runtime._inference_sweeper.stop()
    try:
        assert runtime.storage.supports_outbox is True

        # No session_id -> evolve_knowledge creates a fresh session from
        # json_data + the given operations.
        create_result = await evolve_knowledge(
            runtime,
            {
                "json_data": json.dumps({"objects": []}),
                "operations": [
                    {
                        "type": "add_object",
                        "identity": {"id": "thing-1", "type": "Thing", "name": "thing-1"},
                        "structure": {"note": "original"},
                    }
                ],
            },
        )
        assert "error" not in create_result, create_result
        target_session_id = create_result["session_id"]

        branch_result = await create_branch(runtime, {"session_id": target_session_id})
        source_session_id = branch_result["session_id"]
        assert source_session_id != target_session_id

        # Simulate what cks_mcp.gossip._on_conflict's dual-write does
        # when a GossipConflictDetected event fires -- enqueue directly
        # rather than actually running gossip, to keep this test
        # focused on the Critic Agent's own claim/resolve/complete path.
        await runtime.storage.enqueue_task(
            task_type="gossip_conflict",
            session_id=target_session_id,
            payload=json.dumps(
                {
                    "source_replica_id": "peer-1",
                    "source_session_id": source_session_id,
                    "conflicts": ["thing-1"],
                }
            ),
        )

        settings = CriticAgentSettings(poll_interval=0.01, max_retries=3, storage_path=db_path)
        processed = await run_once(runtime, settings)
        assert processed == 1

        # The task is gone (completed), not dead-lettered.
        dead = await runtime.storage.list_dead_letter_tasks(task_type="gossip_conflict")
        assert dead == []
        remaining = await runtime.storage.dequeue_next_outbox_task(task_type="gossip_conflict")
        assert remaining is None
    finally:
        await runtime.aclose()


async def test_run_once_drains_both_queues(mock_runtime):
    """Two gossip tasks then empty, one inference task then empty."""
    gossip_tasks = [
        OutboxTask(task_id=1, task_type="gossip_conflict", session_id="s1", payload="{}", retry_count=0),
        OutboxTask(task_id=2, task_type="gossip_conflict", session_id="s1", payload="{}", retry_count=0),
        None,
    ]
    inference_tasks = [
        OutboxTask(task_id=3, task_type="inference_conflict", session_id="s1", payload="{}", retry_count=0),
        None,
    ]

    async def _dequeue(task_type=None):
        if task_type == "gossip_conflict":
            return gossip_tasks.pop(0)
        return inference_tasks.pop(0)

    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=_dequeue)

    processed = await run_once(mock_runtime, _settings(max_retries=1))

    # Every task fails to resolve (no source_session_id / no arbitrable
    # diagnostics) and immediately dead-letters at max_retries=1 -- the
    # point of this test is that run_once claims all 3 before stopping,
    # not the individual outcomes.
    assert processed == 3
    assert gossip_tasks == []
    assert inference_tasks == []
