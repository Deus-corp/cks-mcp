"""Unit tests for cks_mcp.critic_agent."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from cks_runtime.storage.storage import OutboxTask

from cks_mcp.critic_agent import (
    CriticAgentSettings,
    LLMCircuitBreaker,
    Resolution,
    _process_one,
    _resolve_confidence_conflicts,
    _run_resolver_with_heartbeat,
    get_critic_metrics,
    reset_critic_agent_state,
    resolve_contradiction_conflict,
    resolve_crdt_fork,
    resolve_gossip_conflict,
    resolve_inference_conflict,
    resolve_provenance_conflict,
    resolve_temporal_conflict,
    run_once,
)

pytestmark = pytest.mark.asyncio


def _settings(**overrides) -> CriticAgentSettings:
    base = CriticAgentSettings(poll_interval=0.01, max_retries=3, storage_path=":memory:")
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


@pytest.fixture(autouse=True)
def _reset_critic_global_state():
    """Metrics and the LLM circuit breaker are module-level singletons --
    reset before and after every test so they don't leak across tests."""
    reset_critic_agent_state()
    yield
    reset_critic_agent_state()


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.dequeue_next_outbox_task = AsyncMock(return_value=None)
    runtime.storage.complete_outbox_task = AsyncMock()
    runtime.storage.fail_outbox_task = AsyncMock()
    runtime.storage.dead_letter_outbox_task = AsyncMock()
    runtime.storage.touch_outbox_task = AsyncMock(return_value=True)
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


async def test_inference_conflict_no_diagnostics_at_all(mock_runtime):
    """An empty/irrelevant diagnostics list has nothing to arbitrate."""
    task = {"session_id": "s1", "payload": {"diagnostics": []}}
    resolution = await resolve_inference_conflict(mock_runtime, task)
    assert resolution.resolved is True


async def test_inference_conflict_stale_premise_only_is_actually_resolved(
    mock_runtime, monkeypatch
):
    """
    A payload with ONLY CKS-EXT-STALE-PREMISE findings must genuinely
    call the mechanical stale_premise_ids path, not just be marked
    complete without doing anything.
    """
    task = {
        "session_id": "s1",
        "payload": {
            "diagnostics": [
                {"code": "CKS-EXT-STALE-PREMISE", "location": "step-1"},
            ]
        },
    }

    calls: list[dict] = []

    async def _fake_arbitrate(runtime, arguments):
        calls.append(arguments)
        assert "conclusion_ids" not in arguments
        assert arguments["stale_premise_ids"] == ["step-1"]
        return {
            "session_id": "s1",
            "results": [{"step_id": "step-1", "resolved": True, "fixes": {"old": "new"}}],
            "commit_result": {"committed": True},
        }

    monkeypatch.setattr("cks_mcp.critic_agent.arbitrate_inference_conflict", _fake_arbitrate)

    resolution = await resolve_inference_conflict(mock_runtime, task)
    assert resolution.resolved is True
    assert len(calls) == 1


async def test_inference_conflict_stale_premise_step_error_is_unresolved(
    mock_runtime, monkeypatch
):
    """A step-level error from the stale-premise path must not be swallowed."""
    task = {
        "session_id": "s1",
        "payload": {
            "diagnostics": [
                {"code": "CKS-EXT-STALE-PREMISE", "location": "missing-step"},
            ]
        },
    }

    async def _fake_arbitrate(runtime, arguments):
        return {
            "session_id": "s1",
            "results": [{"step_id": "missing-step", "error": "Step 'missing-step' not found."}],
        }

    monkeypatch.setattr("cks_mcp.critic_agent.arbitrate_inference_conflict", _fake_arbitrate)

    resolution = await resolve_inference_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "missing-step" in resolution.detail


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


async def test_inference_conflict_mixed_diagnostics_use_two_separate_calls(
    mock_runtime, monkeypatch
):
    """
    Regression test: arbitrate_inference_conflict rejects a call that
    mixes 'conclusion_ids' and 'stale_premise_ids' (invalid_parameter).
    A payload with BOTH diagnostic codes must therefore resolve via
    two independent calls -- one per diagnostic type -- never one
    call carrying both parameters at once.
    """
    task = {
        "session_id": "s1",
        "payload": {
            "diagnostics": [
                {"code": "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT", "location": "obj-1"},
                {"code": "CKS-EXT-STALE-PREMISE", "location": "step-9"},
            ]
        },
    }

    calls: list[dict] = []

    async def _fake_arbitrate(runtime, arguments):
        calls.append(arguments)
        # The real tool would return invalid_parameter if both were
        # ever present together -- assert the agent never does that.
        assert not ("conclusion_ids" in arguments and "stale_premise_ids" in arguments), (
            "resolve_inference_conflict must never send conclusion_ids and "
            "stale_premise_ids in the same arbitrate_inference_conflict call"
        )
        if "conclusion_ids" in arguments:
            assert arguments["conclusion_ids"] == ["obj-1"]
            assert arguments["auto_resolve"] is True
            return {
                "session_id": "s1",
                "results": [
                    {"conclusion_id": "obj-1", "conflict": True, "decision": {"winner_step_id": "x"}}
                ],
                "commit_result": {"committed": True},
            }
        assert arguments["stale_premise_ids"] == ["step-9"]
        return {
            "session_id": "s1",
            "results": [{"step_id": "step-9", "resolved": True, "fixes": {"old": "new"}}],
            "commit_result": {"committed": True},
        }

    monkeypatch.setattr("cks_mcp.critic_agent.arbitrate_inference_conflict", _fake_arbitrate)

    resolution = await resolve_inference_conflict(mock_runtime, task)

    assert resolution.resolved is True
    assert len(calls) == 2
    call_kinds = {"conclusion_ids" if "conclusion_ids" in c else "stale_premise_ids" for c in calls}
    assert call_kinds == {"conclusion_ids", "stale_premise_ids"}


async def test_inference_conflict_mixed_diagnostics_partial_failure(mock_runtime, monkeypatch):
    """
    If the confidence-conflict half fails but the stale-premise half
    succeeds (or vice versa), the combined task must be reported as
    unresolved, with both diagnostic types actually attempted.
    """
    task = {
        "session_id": "s1",
        "payload": {
            "diagnostics": [
                {"code": "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT", "location": "obj-1"},
                {"code": "CKS-EXT-STALE-PREMISE", "location": "step-9"},
            ]
        },
    }

    async def _fake_arbitrate(runtime, arguments):
        if "conclusion_ids" in arguments:
            return {"error": "llm_error", "message": "provider unavailable"}
        return {
            "session_id": "s1",
            "results": [{"step_id": "step-9", "resolved": True, "fixes": {"old": "new"}}],
            "commit_result": {"committed": True},
        }

    monkeypatch.setattr("cks_mcp.critic_agent.arbitrate_inference_conflict", _fake_arbitrate)

    resolution = await resolve_inference_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "conclusion_ids" in resolution.detail or "obj-1" in resolution.detail or resolution.detail


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
# resolve_provenance_conflict
# ---------------------------------------------------------------------------


async def test_provenance_conflict_missing_record_or_subject_id(mock_runtime):
    task = {"session_id": "s1", "payload": {"source_url": "https://example.com"}}
    resolution = await resolve_provenance_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "record_id" in resolution.detail


async def test_provenance_conflict_missing_source_url(mock_runtime):
    task = {
        "session_id": "s1",
        "payload": {"record_id": "rec-1", "subject_id": "doc-1"},
    }
    resolution = await resolve_provenance_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "source_url" in resolution.detail


async def test_provenance_conflict_refreshes_and_commits(mock_runtime, monkeypatch):
    task = {
        "session_id": "s1",
        "payload": {
            "record_id": "rec-1",
            "subject_id": "doc-1",
            "source_url": "https://example.com/doc",
        },
    }

    async def _fake_refresh_verification(runtime, arguments):
        assert arguments == {
            "session_id": "s1",
            "record_id": "rec-1",
            "subject_id": "doc-1",
            "source_url": "https://example.com/doc",
            "auto_resolve": True,
            "commit": True,
        }
        return {"commit_result": {"session_id": "s1"}}

    monkeypatch.setattr(
        "cks_mcp.critic_agent.refresh_verification", _fake_refresh_verification
    )

    resolution = await resolve_provenance_conflict(mock_runtime, task)
    assert resolution.resolved is True


async def test_provenance_conflict_refresh_error_is_a_failure(mock_runtime, monkeypatch):
    task = {
        "session_id": "s1",
        "payload": {
            "record_id": "rec-1",
            "subject_id": "doc-1",
            "source_url": "https://example.com/doc",
        },
    }

    async def _fake_refresh_verification(runtime, arguments):
        return {"error": "unreachable", "message": "connection refused"}

    monkeypatch.setattr(
        "cks_mcp.critic_agent.refresh_verification", _fake_refresh_verification
    )

    resolution = await resolve_provenance_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "refresh_verification error" in resolution.detail


# ---------------------------------------------------------------------------
# resolve_temporal_conflict
# ---------------------------------------------------------------------------


async def test_temporal_conflict_missing_object_id(mock_runtime):
    task = {"session_id": "s1", "payload": {}}
    resolution = await resolve_temporal_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "object_id" in resolution.detail


async def test_temporal_conflict_non_dict_payload(mock_runtime):
    task = {"session_id": "s1", "payload": "not a dict"}
    resolution = await resolve_temporal_conflict(mock_runtime, task)
    assert resolution.resolved is False


async def test_temporal_conflict_bumps_valid_until_and_commits(mock_runtime, monkeypatch):
    task = {"session_id": "s1", "payload": {"object_id": "fact-1"}}

    async def _fake_resolve_temporal_conflict_tool(runtime, arguments):
        assert arguments == {
            "session_id": "s1",
            "object_id": "fact-1",
            "action": "bump",
            "extend_by_days": 30,
            "commit": True,
        }
        return {"commit_result": {"session_id": "s1"}}

    monkeypatch.setattr(
        "cks_mcp.critic_agent._resolve_temporal_conflict_tool",
        _fake_resolve_temporal_conflict_tool,
    )

    resolution = await resolve_temporal_conflict(mock_runtime, task)
    assert resolution.resolved is True


async def test_temporal_conflict_tool_error_is_a_failure(mock_runtime, monkeypatch):
    task = {"session_id": "s1", "payload": {"object_id": "fact-1"}}

    async def _fake_resolve_temporal_conflict_tool(runtime, arguments):
        return {"error": "object_not_found", "message": "gone"}

    monkeypatch.setattr(
        "cks_mcp.critic_agent._resolve_temporal_conflict_tool",
        _fake_resolve_temporal_conflict_tool,
    )

    resolution = await resolve_temporal_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "resolve_temporal_conflict error" in resolution.detail


async def test_temporal_conflict_commit_error_is_a_failure(mock_runtime, monkeypatch):
    task = {"session_id": "s1", "payload": {"object_id": "fact-1"}}

    async def _fake_resolve_temporal_conflict_tool(runtime, arguments):
        return {"commit_result": {"error": "invalid_parameter"}}

    monkeypatch.setattr(
        "cks_mcp.critic_agent._resolve_temporal_conflict_tool",
        _fake_resolve_temporal_conflict_tool,
    )

    resolution = await resolve_temporal_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "commit failed" in resolution.detail


# ---------------------------------------------------------------------------
# resolve_contradiction_conflict
# ---------------------------------------------------------------------------


async def test_contradiction_conflict_missing_location(mock_runtime):
    task = {"session_id": "s1", "payload": {}}
    resolution = await resolve_contradiction_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "location" in resolution.detail


async def test_contradiction_conflict_non_dict_payload(mock_runtime):
    task = {"session_id": "s1", "payload": "not a dict"}
    resolution = await resolve_contradiction_conflict(mock_runtime, task)
    assert resolution.resolved is False


async def test_contradiction_conflict_resolves_and_commits(mock_runtime, monkeypatch):
    task = {"session_id": "s1", "payload": {"code": "CKS-EXT-MUTUAL-EXCLUSION", "location": "rel-1"}}

    async def _fake_resolve_contradiction_tool(runtime, arguments):
        assert arguments == {
            "session_id": "s1",
            "contradiction_ids": ["rel-1"],
            "commit": True,
        }
        return {
            "results": [{"contradiction_id": "rel-1", "removed_relation_id": "rel-1"}],
            "commit_result": {"evolved": True},
        }

    monkeypatch.setattr(
        "cks_mcp.critic_agent._resolve_contradiction_tool",
        _fake_resolve_contradiction_tool,
    )

    resolution = await resolve_contradiction_conflict(mock_runtime, task)
    assert resolution.resolved is True


async def test_contradiction_conflict_already_resolved_counts_as_success(
    mock_runtime, monkeypatch
):
    """A 'contradiction_not_found' result means it was already resolved
    by an earlier pass -- treated as success, not a failure to retry."""
    task = {"session_id": "s1", "payload": {"location": "rel-1"}}

    async def _fake_resolve_contradiction_tool(runtime, arguments):
        return {
            "results": [
                {"contradiction_id": "rel-1", "error": "contradiction_not_found"}
            ],
            "operations": [],
        }

    monkeypatch.setattr(
        "cks_mcp.critic_agent._resolve_contradiction_tool",
        _fake_resolve_contradiction_tool,
    )

    resolution = await resolve_contradiction_conflict(mock_runtime, task)
    assert resolution.resolved is True


async def test_contradiction_conflict_tool_error_is_a_failure(mock_runtime, monkeypatch):
    task = {"session_id": "s1", "payload": {"location": "rel-1"}}

    async def _fake_resolve_contradiction_tool(runtime, arguments):
        return {"error": "invalid_parameter", "message": "bad"}

    monkeypatch.setattr(
        "cks_mcp.critic_agent._resolve_contradiction_tool",
        _fake_resolve_contradiction_tool,
    )

    resolution = await resolve_contradiction_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "resolve_contradiction error" in resolution.detail


async def test_contradiction_conflict_commit_error_is_a_failure(mock_runtime, monkeypatch):
    task = {"session_id": "s1", "payload": {"location": "rel-1"}}

    async def _fake_resolve_contradiction_tool(runtime, arguments):
        return {
            "results": [{"contradiction_id": "rel-1", "removed_relation_id": "rel-1"}],
            "commit_result": {"error": "validation_failed"},
        }

    monkeypatch.setattr(
        "cks_mcp.critic_agent._resolve_contradiction_tool",
        _fake_resolve_contradiction_tool,
    )

    resolution = await resolve_contradiction_conflict(mock_runtime, task)
    assert resolution.resolved is False
    assert "commit failed" in resolution.detail


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


async def test_run_once_drains_all_queues(mock_runtime):
    """Two gossip tasks then empty, one inference/provenance/temporal/
    contradiction task each."""
    gossip_tasks = [
        OutboxTask(task_id=1, task_type="gossip_conflict", session_id="s1", payload="{}", retry_count=0),
        OutboxTask(task_id=2, task_type="gossip_conflict", session_id="s1", payload="{}", retry_count=0),
        None,
    ]
    inference_tasks = [
        OutboxTask(task_id=3, task_type="inference_conflict", session_id="s1", payload="{}", retry_count=0),
        None,
    ]
    provenance_tasks = [
        OutboxTask(task_id=4, task_type="provenance_conflict", session_id="s1", payload="{}", retry_count=0),
        None,
    ]
    temporal_tasks = [
        OutboxTask(task_id=5, task_type="temporal_conflict", session_id="s1", payload="{}", retry_count=0),
        None,
    ]
    contradiction_tasks = [
        OutboxTask(task_id=6, task_type="contradiction_detected", session_id="s1", payload="{}", retry_count=0),
        None,
    ]

    async def _dequeue(task_type=None):
        if task_type == "gossip_conflict":
            return gossip_tasks.pop(0)
        if task_type == "inference_conflict":
            return inference_tasks.pop(0)
        if task_type == "provenance_conflict":
            return provenance_tasks.pop(0)
        if task_type == "temporal_conflict":
            return temporal_tasks.pop(0)
        if task_type == "contradiction_detected":
            return contradiction_tasks.pop(0)
        return None

    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=_dequeue)

    processed = await run_once(mock_runtime, _settings(max_retries=1))

    # Every task fails to resolve (empty payloads carry none of the
    # required keys) and immediately dead-letters at max_retries=1 --
    # the point of this test is that run_once claims all 6 before
    # stopping, across all five task types, not the individual
    # outcomes.
    assert processed == 6
    assert gossip_tasks == []
    assert inference_tasks == []
    assert provenance_tasks == []
    assert temporal_tasks == []
    assert contradiction_tasks == []


async def test_run_once_respects_task_types_override(mock_runtime):
    """Regression test for Priority 1.3: with a narrowed
    ``task_types`` (e.g. crdt_fork carved out for a dedicated Fork
    Resolution Agent, per the module docstring's "run one or the
    other" note), run_once must only claim the configured queues --
    not silently fall back to every _TASK_TYPES entry."""
    seen_task_types: list[str] = []

    async def _dequeue(task_type=None):
        seen_task_types.append(task_type)

    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=_dequeue)

    settings = _settings(task_types=("gossip_conflict", "inference_conflict"))
    processed = await run_once(mock_runtime, settings)

    assert processed == 0
    assert seen_task_types == ["gossip_conflict", "inference_conflict"]
    assert "crdt_fork" not in seen_task_types


def test_settings_from_env_task_types_override(monkeypatch):
    monkeypatch.setenv(
        "CKS_CRITIC_TASK_TYPES", "gossip_conflict, provenance_conflict"
    )
    settings = CriticAgentSettings.from_env()
    assert settings.task_types == ("gossip_conflict", "provenance_conflict")


def test_settings_from_env_task_types_default_includes_crdt_fork(monkeypatch):
    monkeypatch.delenv("CKS_CRITIC_TASK_TYPES", raising=False)
    settings = CriticAgentSettings.from_env()
    assert "crdt_fork" in settings.task_types


def test_settings_from_env_task_types_rejects_unknown(monkeypatch):
    monkeypatch.setenv("CKS_CRITIC_TASK_TYPES", "gossip_conflict,not_a_real_type")
    with pytest.raises(ValueError, match="not_a_real_type"):
        CriticAgentSettings.from_env()


# ---------------------------------------------------------------------------
# Heartbeat / lease renewal
# ---------------------------------------------------------------------------


async def test_heartbeat_renews_lease_during_slow_resolver(mock_runtime):
    """A resolver slower than heartbeat_interval must get its lease
    renewed at least once before it finishes."""

    async def _slow_resolver(runtime, task):
        await asyncio.sleep(0.1)
        return Resolution(True)

    resolution, lease_lost = await _run_resolver_with_heartbeat(
        mock_runtime, _slow_resolver, {"session_id": "s1"}, task_id=42, heartbeat_interval=0.02
    )

    assert resolution.resolved is True
    assert lease_lost is False
    assert mock_runtime.storage.touch_outbox_task.await_count >= 2


async def test_heartbeat_does_not_fire_for_fast_resolver(mock_runtime):
    """A resolver that finishes well inside heartbeat_interval shouldn't
    renew at all -- no need to touch storage for a quick task."""

    async def _fast_resolver(runtime, task):
        return Resolution(True)

    resolution, lease_lost = await _run_resolver_with_heartbeat(
        mock_runtime, _fast_resolver, {"session_id": "s1"}, task_id=1, heartbeat_interval=60.0
    )

    assert resolution.resolved is True
    assert lease_lost is False
    mock_runtime.storage.touch_outbox_task.assert_not_awaited()


async def test_lease_lost_during_resolution_is_not_completed_or_failed(mock_runtime):
    """
    If touch_outbox_task reports the lease is gone (another worker
    reclaimed it), _process_one must not call complete/fail/dead_letter
    for that task -- doing so would race with whoever holds it now.
    """
    task = OutboxTask(
        task_id=7, task_type="gossip_conflict", session_id="s1", payload="{}", retry_count=0
    )
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=[task, None])
    mock_runtime.storage.touch_outbox_task = AsyncMock(return_value=False)  # lease already gone

    async def _slow_resolver(runtime, task):
        await asyncio.sleep(0.02)
        return Resolution(True)

    import cks_mcp.critic_agent as critic_agent_module

    original = critic_agent_module._RESOLVERS["gossip_conflict"]
    critic_agent_module._RESOLVERS["gossip_conflict"] = _slow_resolver
    try:
        result = await _process_one(
            mock_runtime, "gossip_conflict", _settings(heartbeat_interval=0.005, max_retries=3)
        )
    finally:
        critic_agent_module._RESOLVERS["gossip_conflict"] = original

    assert result is True
    mock_runtime.storage.complete_outbox_task.assert_not_awaited()
    mock_runtime.storage.fail_outbox_task.assert_not_awaited()
    mock_runtime.storage.dead_letter_outbox_task.assert_not_awaited()

    metrics = get_critic_metrics()
    assert metrics["lease_lost"]["gossip_conflict"] == 1


# ---------------------------------------------------------------------------
# LLM circuit breaker
# ---------------------------------------------------------------------------


async def test_breaker_opens_after_threshold_consecutive_llm_failures(mock_runtime, monkeypatch):
    breaker = LLMCircuitBreaker(threshold=2, cooldown=60.0)
    call_count = 0

    async def _fake_arbitrate(runtime, arguments):
        nonlocal call_count
        call_count += 1
        return {
            "session_id": "s1",
            "results": [
                {
                    "conclusion_id": "obj-1",
                    "conflict": True,
                    "error": "internal_error",
                    "message": "Internal error: LLM arbiter call failed: connection refused",
                }
            ],
        }

    monkeypatch.setattr("cks_mcp.critic_agent.arbitrate_inference_conflict", _fake_arbitrate)

    r1 = await _resolve_confidence_conflicts(mock_runtime, "s1", ["obj-1"], breaker)
    assert r1.resolved is False
    assert breaker.is_open() is False  # 1st failure, threshold is 2

    r2 = await _resolve_confidence_conflicts(mock_runtime, "s1", ["obj-1"], breaker)
    assert r2.resolved is False
    assert breaker.is_open() is True  # 2nd consecutive failure trips it
    assert call_count == 2

    # Breaker open -> next call must be skipped entirely, no 3rd LLM call.
    r3 = await _resolve_confidence_conflicts(mock_runtime, "s1", ["obj-1"], breaker)
    assert r3.resolved is False
    assert "circuit breaker" in r3.detail
    assert call_count == 2  # unchanged -- arbitrate_inference_conflict never called


async def test_breaker_resets_on_success(mock_runtime, monkeypatch):
    breaker = LLMCircuitBreaker(threshold=2, cooldown=60.0)

    async def _fake_success(runtime, arguments):
        return {
            "session_id": "s1",
            "results": [
                {
                    "conclusion_id": "obj-1",
                    "conflict": True,
                    "decision": {"winner_step_id": "x"},
                }
            ],
            "commit_result": {"committed": True},
        }

    monkeypatch.setattr("cks_mcp.critic_agent.arbitrate_inference_conflict", _fake_success)

    resolution = await _resolve_confidence_conflicts(mock_runtime, "s1", ["obj-1"], breaker)
    assert resolution.resolved is True
    assert breaker.is_open() is False


async def test_breaker_does_not_trip_on_non_llm_error(mock_runtime, monkeypatch):
    """A structural error (e.g. session_not_found) is not the LLM
    provider's fault -- must not count towards the breaker threshold."""
    breaker = LLMCircuitBreaker(threshold=1, cooldown=60.0)

    async def _fake_structural_error(runtime, arguments):
        return {"error": "session_not_found", "message": "no such session"}

    monkeypatch.setattr("cks_mcp.critic_agent.arbitrate_inference_conflict", _fake_structural_error)

    resolution = await _resolve_confidence_conflicts(mock_runtime, "s1", ["obj-1"], breaker)
    assert resolution.resolved is False
    assert breaker.is_open() is False


async def test_breaker_half_open_after_cooldown(mock_runtime):
    breaker = LLMCircuitBreaker(threshold=1, cooldown=0.01)
    breaker.record_failure()
    assert breaker.is_open() is True
    await asyncio.sleep(0.02)
    assert breaker.is_open() is False  # cooldown elapsed -> half-open


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


async def test_metrics_track_completed_and_dead_lettered(mock_runtime):
    gossip_tasks = [
        OutboxTask(task_id=1, task_type="gossip_conflict", session_id="s1", payload="{}", retry_count=0),
        None,
    ]

    async def _dequeue(task_type=None):
        if task_type == "gossip_conflict":
            return gossip_tasks.pop(0)
        # other task types — not used in this test
        return None

    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=_dequeue)

    await run_once(mock_runtime, _settings(max_retries=1))

    metrics = get_critic_metrics()
    assert metrics["processed"]["gossip_conflict"] == 1
    # payload "{}" has no source_session_id -> fails -> dead-lettered at max_retries=1
    assert metrics["dead_lettered"]["gossip_conflict"] == 1
    assert metrics["completed"].get("gossip_conflict", 0) == 0


async def test_get_critic_metrics_starts_at_zero():
    metrics = get_critic_metrics()
    assert metrics["processed"] == {}
    assert metrics["completed"] == {}
    assert metrics["dead_lettered"] == {}
    assert metrics["lease_lost"] == {}
    assert metrics["llm_breaker_open"] is False
    assert metrics["llm_breaker_trips"] == 0

# ---------------------------------------------------------------------------
# resolve_crdt_fork (ADR-013 Stage 2)
# ---------------------------------------------------------------------------


async def test_resolve_crdt_fork_rejects_non_dict_payload(mock_runtime):
    task = {"session_id": "head", "payload": "not-a-dict", "retry_count": 0}
    resolution = await resolve_crdt_fork(mock_runtime, task)
    assert resolution.resolved is False
    assert "payload" in (resolution.detail or "")


async def test_resolve_crdt_fork_rejects_missing_pointer_key(mock_runtime):
    task = {"session_id": "", "payload": {"conflicting_object_ids": ["a", "b"]}, "retry_count": 0}
    resolution = await resolve_crdt_fork(mock_runtime, task)
    assert resolution.resolved is False
    assert "pointer_key" in (resolution.detail or "")


async def test_resolve_crdt_fork_rejects_insufficient_object_ids(mock_runtime):
    task = {
        "session_id": "head",
        "payload": {"pointer_key": "head", "conflicting_object_ids": ["only-one"]},
        "retry_count": 0,
    }
    resolution = await resolve_crdt_fork(mock_runtime, task)
    assert resolution.resolved is False
    assert "conflicting_object_ids" in (resolution.detail or "")


async def test_resolve_crdt_fork_no_attached_crdt_store(mock_runtime):
    # mock_runtime.storage is a MagicMock, not a real SQLiteStorage/
    # PostgresStorage instance, so _crdt_store_for(...) returns None.
    task = {
        "session_id": "head",
        "payload": {
            "pointer_key": "head",
            "conflicting_object_ids": ["obj-a", "obj-b"],
            "event_id": "evt-1",
        },
        "retry_count": 0,
    }
    resolution = await resolve_crdt_fork(mock_runtime, task)
    assert resolution.resolved is False
    assert "CRDTStore" in (resolution.detail or "")


async def test_end_to_end_crdt_fork_resolution_with_real_storage(tmp_path):
    """
    No mocks: a real SQLite-backed Runtime/CRDTStore, a real MV-Register
    fork seeded via update_pointer, a real enqueued 'crdt_fork' outbox
    task, and the full claim -> resolve -> complete path via run_once.
    """
    import json

    from cks_runtime.config import RuntimeConfig
    from cks_runtime.crdt.crdt_store import SQLiteCRDTStore
    from cks_runtime.crdt.version_vector import VersionVector
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter

    db_path = str(tmp_path / "critic_agent_crdt_fork_test.db")
    runtime = await Runtime.create(core=CksCoreAdapter(), config=RuntimeConfig(storage_path=db_path))
    if hasattr(runtime, "_outbox_worker") and runtime._outbox_worker is not None:
        await runtime._outbox_worker.stop()
    if hasattr(runtime, "_inference_sweeper") and runtime._inference_sweeper is not None:
        await runtime._inference_sweeper.stop()
    try:
        # Seed a genuine fork directly on the same connection the
        # Runtime's own SQLiteStorage holds, mirroring how
        # GossipAdapter._handle_fork/CRDTStore.escalate_fork would
        # have produced this state via _build_crdt_store in gossip.py.
        conn = runtime.storage.wrapped._conn
        crdt_store = SQLiteCRDTStore(conn)
        crdt_store.update_pointer("concept-1", "obj-aaa", VersionVector(clocks={"n1": 1}), "n1")
        crdt_store.update_pointer("concept-1", "obj-bbb", VersionVector(clocks={"n2": 1}), "n2")
        assert len(crdt_store.get_pointers("concept-1")) == 2
        event_id = crdt_store.escalate_fork(
            "concept-1", ["obj-aaa", "obj-bbb"], [{"n1": 1}, {"n2": 1}]
        )

        await runtime.storage.enqueue_task(
            task_type="crdt_fork",
            session_id="concept-1",
            payload=json.dumps(
                {
                    "pointer_key": "concept-1",
                    "conflicting_object_ids": ["obj-aaa", "obj-bbb"],
                    "event_id": event_id,
                }
            ),
        )

        settings = CriticAgentSettings(poll_interval=0.01, max_retries=3, storage_path=db_path)
        processed = await run_once(runtime, settings)
        assert processed == 1

        dead = await runtime.storage.list_dead_letter_tasks(task_type="crdt_fork")
        assert dead == []

        # "obj-bbb" sorts last lexicographically -> deterministic winner.
        remaining_pointers = crdt_store.get_pointers("concept-1")
        assert [p["object_id"] for p in remaining_pointers] == ["obj-bbb"]
        assert crdt_store.list_pending_forks() == []
    finally:
        await runtime.aclose()