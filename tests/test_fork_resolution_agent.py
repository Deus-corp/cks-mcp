"""Unit tests for the Fork Resolution Agent (ADR-013 Stage 3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cks_mcp.fork_resolution_agent import (
    ForkResolutionAgentSettings,
    _find_causally_newest,
    _resolution_object_exists,
    _select_winner,
    _try_lca_resolution,
    resolve_fork,
    run_once,
)

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**overrides) -> ForkResolutionAgentSettings:
    base = ForkResolutionAgentSettings(
        poll_interval=0.01, max_retries=3, storage_path=":memory:"
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _make_crdt_store_mock():
    store = MagicMock()
    store.get_object = AsyncMock(return_value={"identity": {"id": "test"}})
    store.get_pointers = AsyncMock(return_value=[])
    store.resolve_pointer = AsyncMock(return_value=True)
    store.mark_fork_resolved = AsyncMock(return_value=None)
    return store


# ---------------------------------------------------------------------------
# LCA resolution-object idempotency (Priority 1.1)
# ---------------------------------------------------------------------------


class _FakeStructure:
    def __init__(self, ids: set[str]):
        self._ids = ids

    def __contains__(self, item: str) -> bool:
        return item in self._ids


class _FakeSession:
    def __init__(self, ids: set[str]):
        self.knowledge_structure = _FakeStructure(ids)


def test_resolution_object_exists_true_when_present():
    runtime = MagicMock()
    runtime.get_session = MagicMock(return_value=_FakeSession({"resolution-abc123"}))
    assert _resolution_object_exists(runtime, "s1", "resolution-abc123") is True


def test_resolution_object_exists_false_when_absent():
    runtime = MagicMock()
    runtime.get_session = MagicMock(return_value=_FakeSession({"other-id"}))
    assert _resolution_object_exists(runtime, "s1", "resolution-abc123") is False


def test_resolution_object_exists_false_when_no_session():
    runtime = MagicMock()
    runtime.get_session = MagicMock(return_value=None)
    assert _resolution_object_exists(runtime, "s1", "resolution-abc123") is False


class TestLcaResolutionIdempotency:
    """Regression tests for the 'Object ... already exists' class of
    bug (Priority 1.1): _try_lca_resolution's resolution-object write
    uses a deterministic id, so a retried fork task must not
    re-attempt (and silently ignore an 'already exists' failure on) a
    write that already succeeded."""

    def _lca_resolution(self, *, resolution_object=None, winner="obj-a"):
        result = MagicMock()
        result.resolved = True
        result.resolution_object = resolution_object
        result.winner_object_id = winner
        result.detail = "lca picked a winner"
        return result

    async def test_skips_evolve_when_resolution_object_already_recorded(self, monkeypatch):
        resolution_object = {
            "identity": {"id": "resolution-dup", "type": "Resolution", "name": "x"},
            "structure": {},
        }
        runtime = MagicMock()
        # session already contains resolution-dup -- e.g. this is a
        # retry after the write committed but the outbox task crashed
        # before being marked complete.
        session = _FakeSession({"obj-a", "obj-b", "resolution-dup"})
        runtime.get_session = MagicMock(return_value=session)
        runtime.list_sessions = MagicMock(return_value=[])

        monkeypatch.setattr(
            "cks_mcp.fork_resolution_agent._find_owning_session_id",
            lambda *_a, **_k: "s1",
        )
        evolve_mock = AsyncMock()
        monkeypatch.setattr("cks_mcp.fork_resolution_agent.evolve_knowledge", evolve_mock)
        monkeypatch.setattr(
            "cks_mcp.fork_resolution_agent.resolve_with_lca",
            AsyncMock(return_value=self._lca_resolution(resolution_object=resolution_object)),
        )

        winner, _detail = await _try_lca_resolution(runtime, ["obj-a", "obj-b"])

        assert winner == "obj-a"
        evolve_mock.assert_not_called()

    async def test_writes_resolution_object_when_not_yet_recorded(self, monkeypatch):
        resolution_object = {
            "identity": {"id": "resolution-new", "type": "Resolution", "name": "x"},
            "structure": {},
        }
        runtime = MagicMock()
        session = _FakeSession({"obj-a", "obj-b"})  # resolution-new not present yet
        runtime.get_session = MagicMock(return_value=session)
        runtime.list_sessions = MagicMock(return_value=[])

        monkeypatch.setattr(
            "cks_mcp.fork_resolution_agent._find_owning_session_id",
            lambda *_a, **_k: "s1",
        )
        evolve_mock = AsyncMock(return_value={"ok": True})
        monkeypatch.setattr("cks_mcp.fork_resolution_agent.evolve_knowledge", evolve_mock)
        monkeypatch.setattr(
            "cks_mcp.fork_resolution_agent.resolve_with_lca",
            AsyncMock(return_value=self._lca_resolution(resolution_object=resolution_object)),
        )

        winner, _detail = await _try_lca_resolution(runtime, ["obj-a", "obj-b"])

        assert winner == "obj-a"
        evolve_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Causality-based winner selection
# ---------------------------------------------------------------------------


class TestCausalityWinner:
    def test_single_candidate_is_itself(self):
        candidates = [
            {
                "object_id": "a",
                "vv": MagicMock(),
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]
        assert _find_causally_newest(candidates) == "a"

    def test_dominating_candidate_wins(self):
        dom_vv = MagicMock()
        sub_vv = MagicMock()

        with patch(
            "cks_mcp.fork_resolution_agent.causality_check",
            side_effect=["dominates", "dominates", "dominated", "dominated"],
        ):
            candidates = [
                {"object_id": "winner", "vv": dom_vv, "created_at": "2026-01-01T00:00:00Z"},
                {"object_id": "loser", "vv": sub_vv, "created_at": "2026-01-01T00:00:00Z"},
            ]
            assert _find_causally_newest(candidates) == "winner"

    def test_concurrent_vectors_return_none(self):
        with patch(
            "cks_mcp.fork_resolution_agent.causality_check",
            return_value="concurrent",
        ):
            candidates = [
                {"object_id": "a", "vv": MagicMock(), "created_at": "2026-01-01T00:00:00Z"},
                {"object_id": "b", "vv": MagicMock(), "created_at": "2026-01-01T00:00:00Z"},
            ]
            assert _find_causally_newest(candidates) is None


# ---------------------------------------------------------------------------
# select_winner (full tie-break chain)
# ---------------------------------------------------------------------------


class TestSelectWinner:
    def test_newest_timestamp_wins_when_causality_fails(self):
        candidates = [
            {"object_id": "old", "vv": MagicMock(), "created_at": "2026-01-01T00:00:00Z"},
            {"object_id": "new", "vv": MagicMock(), "created_at": "2026-01-02T00:00:00Z"},
        ]
        with patch(
            "cks_mcp.fork_resolution_agent._find_causally_newest", return_value=None
        ):
            assert _select_winner(candidates) == "new"

    def test_identical_timestamps_fall_back_to_alphabetical(self):
        candidates = [
            {"object_id": "z-first", "vv": MagicMock(), "created_at": "2026-01-01T00:00:00Z"},
            {"object_id": "a-second", "vv": MagicMock(), "created_at": "2026-01-01T00:00:00Z"},
        ]
        with patch(
            "cks_mcp.fork_resolution_agent._find_causally_newest", return_value=None
        ):
            # Alphabetically first wins: "a-second" < "z-first"
            assert _select_winner(candidates) == "a-second"

    def test_missing_timestamps_fall_back_to_alphabetical(self):
        candidates = [
            {"object_id": "z-first", "vv": MagicMock(), "created_at": None},
            {"object_id": "a-second", "vv": MagicMock(), "created_at": None},
        ]
        with patch(
            "cks_mcp.fork_resolution_agent._find_causally_newest", return_value=None
        ):
            assert _select_winner(candidates) == "a-second"


# ---------------------------------------------------------------------------
# resolve_fork
# ---------------------------------------------------------------------------


class TestResolveFork:
    async def test_missing_pointer_key(self):
        task = {"payload": {"conflicting_object_ids": ["a", "b"]}}
        resolution = await resolve_fork(MagicMock(), task)
        assert resolution.resolved is False
        assert "pointer_key" in resolution.detail

    async def test_fewer_than_two_conflicting_ids(self):
        task = {"payload": {"pointer_key": "key1", "conflicting_object_ids": ["a"]}}
        resolution = await resolve_fork(MagicMock(), task)
        assert resolution.resolved is False

    async def test_no_candidate_objects_still_exist(self):
        store = _make_crdt_store_mock()
        store.get_object = AsyncMock(return_value=None)  # all objects gone

        with patch(
            "cks_mcp.fork_resolution_agent._crdt_store_for", return_value=store
        ):
            task = {
                "payload": {
                    "pointer_key": "key1",
                    "conflicting_object_ids": ["a", "b"],
                    "event_id": "ev1",
                }
            }
            resolution = await resolve_fork(MagicMock(), task)

        assert resolution.resolved is True
        store.mark_fork_resolved.assert_awaited_once_with("ev1")

    async def test_single_surviving_candidate_resolves_immediately(self):
        store = _make_crdt_store_mock()
        store.get_object = AsyncMock(side_effect=[None, {"identity": {"id": "b"}}])

        with patch(
            "cks_mcp.fork_resolution_agent._crdt_store_for", return_value=store
        ):
            task = {
                "payload": {
                    "pointer_key": "key1",
                    "conflicting_object_ids": ["a", "b"],
                    "event_id": "ev1",
                }
            }
            resolution = await resolve_fork(MagicMock(), task)

        assert resolution.resolved is True
        store.resolve_pointer.assert_awaited_once_with("key1", "b")

    async def test_no_crdt_store_available(self):
        with patch("cks_mcp.fork_resolution_agent._crdt_store_for", return_value=None):
            task = {
                "payload": {
                    "pointer_key": "key1",
                    "conflicting_object_ids": ["a", "b"],
                }
            }
            resolution = await resolve_fork(MagicMock(), task)

        assert resolution.resolved is False
        assert "no attached CRDTStore" in resolution.detail


# ---------------------------------------------------------------------------
# run_once
# ---------------------------------------------------------------------------


class TestRunOnce:
    async def test_empty_queue_returns_zero(self):
        runtime = MagicMock()
        runtime.storage.supports_outbox = True
        runtime.storage.dequeue_next_outbox_task = AsyncMock(return_value=None)

        processed = await run_once(runtime, _settings())

        assert processed == 0

    async def test_processes_tasks_until_empty(self):
        from cks_runtime.storage.storage import OutboxTask

        tasks = [
            OutboxTask(
                task_id=1,
                task_type="crdt_fork",
                session_id="ptr1",
                payload='{"pointer_key":"ptr1","conflicting_object_ids":["a","b"]}',
                retry_count=0,
            ),
            OutboxTask(
                task_id=2,
                task_type="crdt_fork",
                session_id="ptr2",
                payload='{"pointer_key":"ptr2","conflicting_object_ids":["c","d"]}',
                retry_count=0,
            ),
            None,
        ]

        runtime = MagicMock()
        runtime.storage.supports_outbox = True
        runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=tasks)
        runtime.storage.complete_outbox_task = AsyncMock()
        runtime.storage.fail_outbox_task = AsyncMock()
        runtime.storage.dead_letter_outbox_task = AsyncMock()
        runtime.storage.touch_outbox_task = AsyncMock(return_value=True)

        store = _make_crdt_store_mock()
        with patch(
            "cks_mcp.fork_resolution_agent._crdt_store_for", return_value=store
        ):
            processed = await run_once(runtime, _settings(max_retries=1))

        assert processed == 2