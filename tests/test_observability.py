"""
Unit tests for cks_mcp.observability.log_tool_call.

Covers:
- error_type recorded for a structured {"error": "<code>"} result uses
  the error code itself (regression test for a bug where it was
  recorded as the literal string "str" via type(error_str).__name__).
- error_type recorded for a raised exception uses the exception's
  class name.
- Successful calls record no error_type.
- setup_event_subscriptions wires InferenceConflictDetected (ADR-009)
  into conflict_inbox, unconditionally (unlike GossipConflictDetected,
  which only lands there when gossip is explicitly enabled -- see
  test_gossip.py).
"""

from __future__ import annotations

import json

import pytest
from cks_runtime.events.runtime_event import InferenceConflictDetected
from cks_runtime.runtime import Runtime
from cks_runtime.storage.memory_storage import InMemoryStorage
from cks_runtime.storage.sqlite_storage import SQLiteStorage
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.conflict_inbox import conflict_inbox
from cks_mcp.observability import log_tool_call, setup_event_subscriptions
from cks_mcp.telemetry import tool_telemetry

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _reset_telemetry():
    """log_tool_call always writes to the process-level singleton, so
    each test starts from a clean slate and any state it adds is
    cleared afterwards too."""
    await tool_telemetry.reset()
    yield
    await tool_telemetry.reset()


async def test_structured_error_records_error_code_as_error_type():
    @log_tool_call("fake_tool")
    async def handler(runtime, arguments):
        return {"error": "session_not_found", "message": "Session x not found."}

    await handler(None, {"session_id": "nonexistent"})

    dashboard = await tool_telemetry.dashboard()
    top_errors = dashboard["tools"]["fake_tool"]["top_errors"]
    assert top_errors == [{"type": "session_not_found", "count": 1}]


async def test_raised_exception_records_exception_class_as_error_type():
    @log_tool_call("fake_tool")
    async def handler(runtime, arguments):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await handler(None, {})

    dashboard = await tool_telemetry.dashboard()
    top_errors = dashboard["tools"]["fake_tool"]["top_errors"]
    assert top_errors == [{"type": "ValueError", "count": 1}]


async def test_successful_call_records_no_error():
    @log_tool_call("fake_tool")
    async def handler(runtime, arguments):
        return {"ok": True}

    await handler(None, {})

    dashboard = await tool_telemetry.dashboard()
    stats = dashboard["tools"]["fake_tool"]
    assert stats["error_count"] == 0
    assert stats["top_errors"] == []


async def test_inference_conflict_dual_writes_to_outbox_when_supported(tmp_path):
    """When the storage backend supports the outbox (SQLite/Postgres),
    InferenceConflictDetected must also land there as an
    "inference_conflict" task -- not just conflict_inbox -- so an
    external Critic-agent process sharing the same backend can see it
    via claim_conflict_task, same rationale as the gossip-conflict
    dual-write (test_gossip.py)."""
    await conflict_inbox.reset()
    storage = SQLiteStorage(str(tmp_path / "inference_dualwrite.db"))
    runtime = await Runtime.create(core=CksCoreAdapter(), storage=storage)
    # Stop the background worker so it doesn't steal tasks before the test can check them
    if hasattr(runtime, '_outbox_worker') and runtime._outbox_worker is not None:
        await runtime._outbox_worker.stop()
    try:
        setup_event_subscriptions(runtime)
        assert runtime.storage.supports_outbox is True

        await runtime.events.publish(
            InferenceConflictDetected(
                session_id="session-42",
                version_id="v1",
                diagnostics=[
                    {
                        "code": "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT",
                        "severity": "WARNING",
                        "message": "reach conclusion 'concl-1' with disagreeing confidence",
                        "location": "step-a",
                    }
                ],
            )
        )

        # Same-process readers still see it via conflict_inbox...
        buffered = await conflict_inbox.list_inference(drain=False)
        assert len(buffered) == 1

        # ...and it is also durably queryable from the shared outbox.
        task = await runtime.storage.dequeue_next_outbox_task(task_type="inference_conflict")
        assert task is not None
        assert task.session_id == "session-42"
        payload = json.loads(task.payload)
        assert payload["version_id"] == "v1"
        assert payload["diagnostics"][0]["code"] == "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT"
    finally:
        await conflict_inbox.reset()
        await runtime.aclose()


async def test_inference_conflict_under_inmemory_storage_only_writes_conflict_inbox():
    """InMemoryStorage reports supports_outbox=False, and (unlike
    gossip) the sweeper runs against it by default -- the dual-write
    must no-op silently rather than raise."""
    await conflict_inbox.reset()
    runtime = await Runtime.create(core=CksCoreAdapter(), storage=InMemoryStorage())
    try:
        setup_event_subscriptions(runtime)
        assert runtime.storage.supports_outbox is False

        await runtime.events.publish(
            InferenceConflictDetected(session_id="session-42", version_id="v1", diagnostics=[])
        )

        buffered = await conflict_inbox.list_inference(drain=False)
        assert len(buffered) == 1
    finally:
        await conflict_inbox.reset()
        await runtime.aclose()
    """setup_event_subscriptions must subscribe InferenceConflictDetected
    -> conflict_inbox with no opt-in flag (unlike GossipConflictDetected,
    which requires CKS_GOSSIP_ENABLED via setup_gossip) -- otherwise a
    background sweeper finding is only ever logged and lost."""
    await conflict_inbox.reset()
    runtime = await Runtime.create(core=CksCoreAdapter(), storage=InMemoryStorage())
    try:
        setup_event_subscriptions(runtime)

        await runtime.events.publish(
            InferenceConflictDetected(
                session_id="session-42",
                version_id="v1",
                diagnostics=[
                    {
                        "code": "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT",
                        "severity": "WARNING",
                        "message": "reach conclusion 'concl-1' with disagreeing confidence",
                        "location": "step-a",
                    }
                ],
            )
        )

        buffered = await conflict_inbox.list_inference(drain=False)
        assert len(buffered) == 1
        assert buffered[0]["session_id"] == "session-42"
        assert buffered[0]["version_id"] == "v1"
        assert buffered[0]["diagnostics"][0]["code"] == (
            "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT"
        )
    finally:
        await conflict_inbox.reset()
        await runtime.aclose()