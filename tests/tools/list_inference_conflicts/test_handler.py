"""Unit tests for the list_inference_conflicts MCP tool."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from cks_runtime.events.runtime_event import InferenceConflictDetected

from cks_mcp.conflict_inbox import conflict_inbox
from cks_mcp.tools.list_inference_conflicts.handler import list_inference_conflicts

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


def _diagnostic(conclusion: str = "concl-1") -> dict:
    return {
        "code": "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT",
        "severity": "WARNING",
        "message": f"2 active InferenceStep(s) reach conclusion '{conclusion}' "
        "with disagreeing confidence values.",
        "location": "step-a",
    }


async def test_empty_inbox_returns_empty_list(mock_runtime):
    result = await list_inference_conflicts(mock_runtime, {})

    assert result == {"conflicts": [], "count": 0}


async def test_returns_buffered_conflict(mock_runtime):
    await conflict_inbox.record_inference(
        InferenceConflictDetected(
            session_id="s1",
            version_id="v1",
            diagnostics=[_diagnostic()],
        )
    )

    result = await list_inference_conflicts(mock_runtime, {})

    assert result["count"] == 1
    assert result["conflicts"][0]["session_id"] == "s1"
    assert result["conflicts"][0]["version_id"] == "v1"
    assert result["conflicts"][0]["diagnostics"][0]["code"] == (
        "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT"
    )
    assert "concl-1" in result["conflicts"][0]["diagnostics"][0]["message"]


async def test_session_id_argument_filters(mock_runtime):
    await conflict_inbox.record_inference(
        InferenceConflictDetected(session_id="s1", version_id="v1", diagnostics=[_diagnostic()])
    )
    await conflict_inbox.record_inference(
        InferenceConflictDetected(session_id="s2", version_id="v1", diagnostics=[_diagnostic()])
    )

    result = await list_inference_conflicts(mock_runtime, {"session_id": "s1"})

    assert result["count"] == 1
    assert result["conflicts"][0]["session_id"] == "s1"


async def test_drains_by_default(mock_runtime):
    await conflict_inbox.record_inference(
        InferenceConflictDetected(session_id="s1", version_id="v1", diagnostics=[_diagnostic()])
    )

    first = await list_inference_conflicts(mock_runtime, {})
    second = await list_inference_conflicts(mock_runtime, {})

    assert first["count"] == 1
    assert second == {"conflicts": [], "count": 0}


async def test_peek_true_does_not_drain(mock_runtime):
    await conflict_inbox.record_inference(
        InferenceConflictDetected(session_id="s1", version_id="v1", diagnostics=[_diagnostic()])
    )

    first = await list_inference_conflicts(mock_runtime, {"peek": True})
    second = await list_inference_conflicts(mock_runtime, {"peek": True})

    assert first["count"] == 1
    assert second["count"] == 1


async def test_does_not_leak_into_gossip_conflicts_queue(mock_runtime):
    """A regression guard: list_inference_conflicts must only ever
    read the inference queue, never the separate gossip one."""
    from cks_mcp.tools.list_gossip_conflicts.handler import list_gossip_conflicts

    await conflict_inbox.record_inference(
        InferenceConflictDetected(session_id="s1", version_id="v1", diagnostics=[_diagnostic()])
    )

    gossip_result = await list_gossip_conflicts(mock_runtime, {})
    assert gossip_result == {"conflicts": [], "count": 0}