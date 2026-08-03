"""
Unit tests for cks_mcp.conflict_inbox.

Covers: recording a GossipConflictDetected event (including its
source_session_id, ADR-008 status update), session_id filtering,
drain-by-default semantics vs. peek, and the max_records eviction cap.
Also covers the parallel InferenceConflictDetected queue (ADR-009):
record_inference/list_inference with the same session_id/drain/peek
semantics, and reset() clearing both queues.
"""

from __future__ import annotations

import pytest
from cks_runtime.events.runtime_event import (
    GossipConflictDetected,
    InferenceConflictDetected,
)

from cks_mcp.conflict_inbox import ConflictInbox

pytestmark = pytest.mark.asyncio


def _event(
    session_id: str,
    *,
    source: str = "replica-a",
    conflicts=None,
    source_session_id: str = "",
) -> GossipConflictDetected:
    return GossipConflictDetected(
        source_replica_id=source,
        session_id=session_id,
        source_session_id=source_session_id,
        conflicts=conflicts if conflicts is not None else ["obj-1"],
    )


def _inference_event(
    session_id: str,
    *,
    version_id: str = "v1",
    diagnostics=None,
) -> InferenceConflictDetected:
    return InferenceConflictDetected(
        session_id=session_id,
        version_id=version_id,
        diagnostics=diagnostics
        if diagnostics is not None
        else [
            {
                "code": "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT",
                "severity": "WARNING",
                "message": "2 active InferenceStep(s) reach conclusion 'concl-1' "
                "with disagreeing confidence values.",
                "location": "step-a",
            }
        ],
    )


async def test_record_then_list_returns_it():
    inbox = ConflictInbox()
    await inbox.record(_event("s1"))

    result = await inbox.list()

    assert len(result) == 1
    assert result[0]["session_id"] == "s1"
    assert result[0]["source_replica_id"] == "replica-a"
    assert result[0]["conflicts"] == ["obj-1"]
    assert result[0]["source_session_id"] == ""
    assert "record_id" in result[0]
    assert "detected_at" in result[0]


async def test_source_session_id_is_carried_through():
    inbox = ConflictInbox()
    await inbox.record(_event("s1", source_session_id="branch-abc"))

    result = await inbox.list()

    assert result[0]["source_session_id"] == "branch-abc"


async def test_list_drains_by_default():
    inbox = ConflictInbox()
    await inbox.record(_event("s1"))

    first = await inbox.list()
    second = await inbox.list()

    assert len(first) == 1
    assert second == []


async def test_peek_does_not_drain():
    inbox = ConflictInbox()
    await inbox.record(_event("s1"))

    first = await inbox.list(drain=False)
    second = await inbox.list(drain=False)

    assert len(first) == 1
    assert len(second) == 1


async def test_session_id_filters_and_only_drains_matching():
    inbox = ConflictInbox()
    await inbox.record(_event("s1"))
    await inbox.record(_event("s2"))

    only_s1 = await inbox.list(session_id="s1")
    assert len(only_s1) == 1
    assert only_s1[0]["session_id"] == "s1"

    # s1 was drained, s2 was left alone
    remaining = await inbox.list(drain=False)
    assert len(remaining) == 1
    assert remaining[0]["session_id"] == "s2"


async def test_reset_clears_everything():
    inbox = ConflictInbox()
    await inbox.record(_event("s1"))
    await inbox.reset()

    assert await inbox.list(drain=False) == []


async def test_eviction_caps_at_max_records():
    inbox = ConflictInbox(max_records=3)
    for i in range(5):
        await inbox.record(_event(f"s{i}"))

    remaining = await inbox.list(drain=False)

    assert len(remaining) == 3
    # Oldest (s0, s1) evicted; newest three kept, in original order.
    assert [r["session_id"] for r in remaining] == ["s2", "s3", "s4"]


# ---------------------------------------------------------------------------
# Inference-conflict queue (ADR-009) -- parallel to the gossip queue above,
# same session_id/drain/peek semantics, separate storage.
# ---------------------------------------------------------------------------


async def test_record_inference_then_list_inference_returns_it():
    inbox = ConflictInbox()
    await inbox.record_inference(_inference_event("s1"))

    result = await inbox.list_inference()

    assert len(result) == 1
    assert result[0]["session_id"] == "s1"
    assert result[0]["version_id"] == "v1"
    assert result[0]["diagnostics"][0]["code"] == "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT"
    assert "concl-1" in result[0]["diagnostics"][0]["message"]
    assert "record_id" in result[0]
    assert "detected_at" in result[0]


async def test_inference_list_drains_by_default():
    inbox = ConflictInbox()
    await inbox.record_inference(_inference_event("s1"))

    first = await inbox.list_inference()
    second = await inbox.list_inference()

    assert len(first) == 1
    assert second == []


async def test_inference_peek_does_not_drain():
    inbox = ConflictInbox()
    await inbox.record_inference(_inference_event("s1"))

    first = await inbox.list_inference(drain=False)
    second = await inbox.list_inference(drain=False)

    assert len(first) == 1
    assert len(second) == 1


async def test_inference_session_id_filters_and_only_drains_matching():
    inbox = ConflictInbox()
    await inbox.record_inference(_inference_event("s1"))
    await inbox.record_inference(_inference_event("s2"))

    only_s1 = await inbox.list_inference(session_id="s1")
    assert len(only_s1) == 1
    assert only_s1[0]["session_id"] == "s1"

    # s1 was drained, s2 was left alone
    remaining = await inbox.list_inference(drain=False)
    assert len(remaining) == 1
    assert remaining[0]["session_id"] == "s2"


async def test_inference_eviction_caps_at_max_records():
    inbox = ConflictInbox(max_records=3)
    for i in range(5):
        await inbox.record_inference(_inference_event(f"s{i}"))

    remaining = await inbox.list_inference(drain=False)

    assert len(remaining) == 3
    assert [r["session_id"] for r in remaining] == ["s2", "s3", "s4"]


async def test_gossip_and_inference_queues_are_independent():
    """Recording to one queue must not affect the other, and reset()
    must clear both."""
    inbox = ConflictInbox()
    await inbox.record(_event("s1"))
    await inbox.record_inference(_inference_event("s1"))

    gossip_only = await inbox.list(drain=False)
    inference_only = await inbox.list_inference(drain=False)
    assert len(gossip_only) == 1
    assert len(inference_only) == 1

    await inbox.reset()

    assert await inbox.list(drain=False) == []
    assert await inbox.list_inference(drain=False) == []