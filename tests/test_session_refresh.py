"""Unit tests for cks_mcp.session_refresh.reload_session_from_storage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.session_refresh import reload_session_from_storage

pytestmark = pytest.mark.asyncio


def _make_runtime(fresh):
    runtime = MagicMock()
    runtime.storage.load_session = AsyncMock(return_value=fresh)
    return runtime


async def test_reload_mutates_session_in_place_when_storage_has_a_copy():
    session = MagicMock()
    session.session_id = "s1"
    session.knowledge_structure = "old"
    session.version_history = ["v1"]
    session.metadata = {"a": 1}
    session.closed = False

    fresh = MagicMock()
    fresh.knowledge_structure = "new"
    fresh.version_history = ["v1", "v2"]
    fresh.metadata = {"a": 2}
    fresh.closed = True

    runtime = _make_runtime(fresh)

    result = await reload_session_from_storage(runtime, session)

    # Same object identity -- every existing reference observes the update.
    assert result is session
    assert session.knowledge_structure == "new"
    assert session.version_history == ["v1", "v2"]
    assert session.metadata == {"a": 2}
    assert session.closed is True
    runtime.storage.load_session.assert_awaited_once_with("s1")


async def test_reload_leaves_session_untouched_when_storage_returns_none():
    session = MagicMock()
    session.session_id = "s1"
    session.knowledge_structure = "only-copy"

    runtime = _make_runtime(None)

    result = await reload_session_from_storage(runtime, session)

    assert result is session
    assert session.knowledge_structure == "only-copy"
