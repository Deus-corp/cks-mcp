"""Unit tests for the list_gossip_conflicts MCP tool."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from cks_runtime.events.runtime_event import GossipConflictDetected

from cks_mcp.conflict_inbox import conflict_inbox
from cks_mcp.tools.list_gossip_conflicts.handler import list_gossip_conflicts

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _clean_inbox():
    """The inbox is a process-level singleton -- isolate each test."""
    await conflict_inbox.reset()
    yield
    await conflict_inbox.reset()


@pytest.fixture
def mock_runtime():
    # The handler never touches the runtime -- it only reads conflict_inbox --
    # but the registry always calls handler(runtime, arguments).
    return MagicMock()


async def test_empty_inbox_returns_empty_list(mock_runtime):
    result = await list_gossip_conflicts(mock_runtime, {})

    assert result == {"conflicts": [], "count": 0}


async def test_returns_buffered_conflict(mock_runtime):
    await conflict_inbox.record(
        GossipConflictDetected(
            source_replica_id="replica-a",
            session_id="s1",
            conflicts=["obj-1"],
        )
    )

    result = await list_gossip_conflicts(mock_runtime, {})

    assert result["count"] == 1
    assert result["conflicts"][0]["session_id"] == "s1"
    assert result["conflicts"][0]["source_replica_id"] == "replica-a"
    assert result["conflicts"][0]["conflicts"] == ["obj-1"]


async def test_session_id_argument_filters(mock_runtime):
    await conflict_inbox.record(
        GossipConflictDetected(source_replica_id="r", session_id="s1", conflicts=["a"])
    )
    await conflict_inbox.record(
        GossipConflictDetected(source_replica_id="r", session_id="s2", conflicts=["b"])
    )

    result = await list_gossip_conflicts(mock_runtime, {"session_id": "s1"})

    assert result["count"] == 1
    assert result["conflicts"][0]["session_id"] == "s1"


async def test_drains_by_default(mock_runtime):
    await conflict_inbox.record(
        GossipConflictDetected(source_replica_id="r", session_id="s1", conflicts=["a"])
    )

    first = await list_gossip_conflicts(mock_runtime, {})
    second = await list_gossip_conflicts(mock_runtime, {})

    assert first["count"] == 1
    assert second == {"conflicts": [], "count": 0}


async def test_peek_true_does_not_drain(mock_runtime):
    await conflict_inbox.record(
        GossipConflictDetected(source_replica_id="r", session_id="s1", conflicts=["a"])
    )

    first = await list_gossip_conflicts(mock_runtime, {"peek": True})
    second = await list_gossip_conflicts(mock_runtime, {"peek": True})

    assert first["count"] == 1
    assert second["count"] == 1
