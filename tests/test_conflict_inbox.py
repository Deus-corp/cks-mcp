"""
Unit tests for cks_mcp.conflict_inbox.

Covers: recording a GossipConflictDetected event, session_id filtering,
drain-by-default semantics vs. peek, and the max_records eviction cap.
"""

from __future__ import annotations

import pytest
from cks_runtime.events.runtime_event import GossipConflictDetected

from cks_mcp.conflict_inbox import ConflictInbox

pytestmark = pytest.mark.asyncio


def _event(session_id: str, *, source: str = "replica-a", conflicts=None) -> GossipConflictDetected:
    return GossipConflictDetected(
        source_replica_id=source,
        session_id=session_id,
        conflicts=conflicts if conflicts is not None else ["obj-1"],
    )


async def test_record_then_list_returns_it():
    inbox = ConflictInbox()
    await inbox.record(_event("s1"))

    result = await inbox.list()

    assert len(result) == 1
    assert result[0]["session_id"] == "s1"
    assert result[0]["source_replica_id"] == "replica-a"
    assert result[0]["conflicts"] == ["obj-1"]
    assert "record_id" in result[0]
    assert "detected_at" in result[0]


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
