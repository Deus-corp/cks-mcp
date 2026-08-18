"""Tests for evolve_knowledge's handling of concurrent session writers
(bug: pipeline tasks staying Queued on ConcurrentModificationError /
'Session already has an active transaction')."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from cks_runtime.storage.storage import ConcurrentModificationError

from cks_mcp.tools.evolve.handler import evolve_knowledge

pytestmark = pytest.mark.asyncio

VALID_OPERATIONS = [
    {
        "type": "add_object",
        "identity": {"id": "obj-2", "type": "Lemma", "name": "New"},
        "structure": {},
    }
]


def _make_structure():
    structure = MagicMock()
    structure.relations.return_value = []
    structure.objects = []
    return structure


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()

    structure = _make_structure()
    session = MagicMock(session_id="s1", diagnostics=[], knowledge_structure=structure)
    runtime.get_session.return_value = session

    fresh_structure = _make_structure()
    fresh_session = MagicMock(
        session_id="s1", knowledge_structure=fresh_structure, version_history=[], metadata={}, closed=False
    )
    runtime.storage.load_session = AsyncMock(return_value=fresh_session)

    runtime.core_bridge.validate.return_value = MagicMock(is_valid=True, diagnostics=[])
    runtime.core_bridge.serialize.return_value = '{"serialized":true}'

    runtime.executor.execute = AsyncMock(
        return_value=MagicMock(status=MagicMock(value="completed"), payload=structure)
    )

    tx = MagicMock(session=session)
    runtime.begin_transaction.return_value = tx
    runtime.transactions.abort = MagicMock()

    return runtime, session


async def test_evolve_knowledge_retries_on_concurrent_modification(mock_runtime, monkeypatch):
    runtime, _session = mock_runtime

    monkeypatch.setattr(
        "cks_mcp.provenance.verify_structure_provenance", lambda structure: []
    )

    version = MagicMock(version_id="v2")
    runtime.commit_transaction = AsyncMock(
        side_effect=[ConcurrentModificationError("s1"), version]
    )

    result = await evolve_knowledge(
        runtime,
        {"session_id": "s1", "operations": VALID_OPERATIONS},
    )

    assert result["evolved"] is True
    assert result["version_id"] == "v2"
    # First failed attempt must not leave a dangling active transaction
    # behind, and must not blind-overwrite storage.
    assert runtime.transactions.abort.call_count == 1
    # Session was reloaded from storage before each retry.
    assert runtime.storage.load_session.await_count >= 1
    assert runtime.commit_transaction.await_count == 2


async def test_evolve_knowledge_gives_up_after_max_retries(mock_runtime, monkeypatch):
    runtime, _session = mock_runtime

    monkeypatch.setattr(
        "cks_mcp.provenance.verify_structure_provenance", lambda structure: []
    )
    # Don't actually sleep through the backoff between retries in tests.
    monkeypatch.setattr("cks_mcp.tools.evolve.handler.asyncio.sleep", AsyncMock())

    runtime.commit_transaction = AsyncMock(
        side_effect=ConcurrentModificationError("s1")
    )

    result = await evolve_knowledge(
        runtime,
        {"session_id": "s1", "operations": VALID_OPERATIONS},
    )

    assert result["error"] == "concurrent_modification"
    # 1 initial attempt + 5 retries = 6 total commit attempts (raised
    # from 2 retries -- see _MAX_COMMIT_RETRIES's docstring for why).
    assert runtime.commit_transaction.await_count == 6
    assert runtime.transactions.abort.call_count == 6


async def test_evolve_knowledge_serializes_same_session_calls(mock_runtime, monkeypatch):
    """Two concurrent evolve_knowledge calls against the SAME session_id
    (e.g. ResearcherStep and ReviewerStep both draining tasks for one
    sandbox session under CKSAgentOrchestrator.run_concurrent) must not
    overlap -- overlapping calls are exactly what causes
    TransactionManager.begin() to raise 'Session already has an active
    transaction.'"""
    runtime, _session = mock_runtime

    monkeypatch.setattr(
        "cks_mcp.provenance.verify_structure_provenance", lambda structure: []
    )

    in_flight = 0
    max_concurrent = 0

    async def fake_commit(tx):
        nonlocal in_flight, max_concurrent
        in_flight += 1
        max_concurrent = max(max_concurrent, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return MagicMock(version_id="v1")

    runtime.commit_transaction = fake_commit

    await asyncio.gather(
        evolve_knowledge(runtime, {"session_id": "s1", "operations": VALID_OPERATIONS}),
        evolve_knowledge(runtime, {"session_id": "s1", "operations": VALID_OPERATIONS}),
    )

    assert max_concurrent == 1


async def test_evolve_knowledge_no_ops_when_already_applied_by_concurrent_writer(
    mock_runtime, monkeypatch
):
    """If a concurrent writer's commit already added the exact object
    this call was trying to add (visible after the post-conflict
    reload), evolve_knowledge should report a successful no-op instead
    of endlessly retrying a commit that would only fail again with
    'already exists' -- see `_operations_already_applied`."""
    runtime, _session = mock_runtime

    monkeypatch.setattr(
        "cks_mcp.provenance.verify_structure_provenance", lambda structure: []
    )
    monkeypatch.setattr("cks_mcp.tools.evolve.handler.asyncio.sleep", AsyncMock())

    runtime.commit_transaction = AsyncMock(
        side_effect=ConcurrentModificationError("s1")
    )

    # After the (single) reload, storage now reflects a structure that
    # already contains the object this evolution was trying to add --
    # simulating a concurrent writer having committed it first.
    already_applied_obj = MagicMock()
    already_applied_obj.identity.id = "obj-2"
    fresh_structure = _make_structure()
    fresh_structure.objects = [already_applied_obj]
    fresh_session = MagicMock(
        session_id="s1",
        knowledge_structure=fresh_structure,
        version_history=[MagicMock(version_id="v-concurrent")],
        metadata={},
        closed=False,
    )
    runtime.storage.load_session = AsyncMock(return_value=fresh_session)

    result = await evolve_knowledge(
        runtime,
        {"session_id": "s1", "operations": VALID_OPERATIONS},
    )

    assert result.get("no_op") is True
    assert result["version"] == "v-concurrent"
    assert "error" not in result
    # Only the first (failed) commit attempt should have happened --
    # the no-op short-circuits before a second commit_transaction call.
    assert runtime.commit_transaction.await_count == 1