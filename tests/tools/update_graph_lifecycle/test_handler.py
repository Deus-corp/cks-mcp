"""Unit tests for the update_graph_lifecycle MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.update_graph_lifecycle.handler import (
    ALLOWED_TRANSITIONS,
    LIFECYCLE_STATES,
    update_graph_lifecycle,
)

pytestmark = pytest.mark.asyncio


def _mock_runtime(record: dict | None):
    runtime = MagicMock()
    runtime.storage.get_graph = AsyncMock(return_value=record)
    runtime.storage.register_graph = AsyncMock(return_value=None)
    return runtime


async def test_missing_name():
    runtime = _mock_runtime(None)
    result = await update_graph_lifecycle(runtime, {"state": "published"})
    assert result.get("error") == "missing_parameter"
    runtime.storage.get_graph.assert_not_called()


async def test_missing_state():
    runtime = _mock_runtime(None)
    result = await update_graph_lifecycle(runtime, {"name": "g1"})
    assert result.get("error") == "missing_parameter"
    runtime.storage.get_graph.assert_not_called()


async def test_invalid_state_value():
    runtime = _mock_runtime(None)
    result = await update_graph_lifecycle(runtime, {"name": "g1", "state": "deleted"})
    assert result.get("error") == "invalid_parameter"
    runtime.storage.get_graph.assert_not_called()


async def test_graph_not_found():
    runtime = _mock_runtime(None)
    result = await update_graph_lifecycle(runtime, {"name": "g1", "state": "published"})
    assert result.get("error") == "graph_not_found"


async def test_allowed_transition_updates_registry():
    runtime = _mock_runtime(
        {
            "name": "g1",
            "session_id": "s1",
            "description": "desc",
            "tags": "t1",
            "public": False,
            "visibility": "private",
            "team": None,
            "lifecycle_state": "draft",
        }
    )

    result = await update_graph_lifecycle(runtime, {"name": "g1", "state": "published"})

    assert result == {
        "updated": True,
        "name": "g1",
        "previous_state": "draft",
        "new_state": "published",
    }
    runtime.storage.register_graph.assert_awaited_once_with(
        name="g1",
        session_id="s1",
        description="desc",
        tags="t1",
        public=False,
        visibility="private",
        team=None,
        lifecycle_state="published",
    )


async def test_disallowed_transition_returns_structured_error():
    runtime = _mock_runtime(
        {
            "name": "g1",
            "session_id": "s1",
            "lifecycle_state": "draft",
        }
    )

    result = await update_graph_lifecycle(runtime, {"name": "g1", "state": "active"})

    assert result["error"] == "invalid_state_transition"
    assert result["name"] == "g1"
    assert result["previous_state"] == "draft"
    assert result["requested_state"] == "active"
    assert set(result["allowed"]) == {"published", "archived"}
    runtime.storage.register_graph.assert_not_called()


async def test_archived_is_terminal():
    runtime = _mock_runtime(
        {
            "name": "g1",
            "session_id": "s1",
            "lifecycle_state": "archived",
        }
    )

    result = await update_graph_lifecycle(runtime, {"name": "g1", "state": "draft"})

    assert result["error"] == "invalid_state_transition"
    assert result["allowed"] == []
    runtime.storage.register_graph.assert_not_called()


async def test_same_state_is_a_noop_not_an_error():
    runtime = _mock_runtime(
        {
            "name": "g1",
            "session_id": "s1",
            "lifecycle_state": "active",
        }
    )

    result = await update_graph_lifecycle(runtime, {"name": "g1", "state": "active"})

    assert result["updated"] is False
    assert result["reason"] == "already in requested state"
    runtime.storage.register_graph.assert_not_called()


async def test_missing_lifecycle_state_defaults_to_draft():
    # A graph registered before this feature existed (or via a backend
    # that hasn't backfilled it yet) has no lifecycle_state key at all.
    runtime = _mock_runtime(
        {
            "name": "g1",
            "session_id": "s1",
        }
    )

    result = await update_graph_lifecycle(runtime, {"name": "g1", "state": "published"})

    assert result["updated"] is True
    assert result["previous_state"] == "draft"


@pytest.mark.parametrize("state", LIFECYCLE_STATES)
async def test_every_state_in_transition_map(state):
    assert state in ALLOWED_TRANSITIONS


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    [
        ("draft", "published"),
        ("draft", "archived"),
        ("published", "active"),
        ("published", "under_review"),
        ("published", "archived"),
        ("active", "stale"),
        ("active", "under_review"),
        ("active", "archived"),
        ("stale", "under_review"),
        ("stale", "active"),
        ("stale", "archived"),
        ("under_review", "active"),
        ("under_review", "published"),
        ("under_review", "archived"),
    ],
)
async def test_full_allowed_transition_matrix(from_state, to_state):
    runtime = _mock_runtime(
        {"name": "g1", "session_id": "s1", "lifecycle_state": from_state}
    )
    result = await update_graph_lifecycle(runtime, {"name": "g1", "state": to_state})
    assert result.get("updated") is True
