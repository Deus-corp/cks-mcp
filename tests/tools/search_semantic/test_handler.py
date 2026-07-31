"""Unit and integration tests for the search_semantic tool."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import cks
import pytest
from cks_runtime.config import RuntimeConfig
from cks_runtime.operations.operation_types import ValidateOperation
from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.tools.search_semantic.handler import search_semantic

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    session = MagicMock(session_id="s1")
    runtime.get_session.return_value = session
    del runtime.storage.search_embeddings
    return runtime


async def test_missing_session_id(mock_runtime):
    result = await search_semantic(mock_runtime, {"query": "fruit"})
    assert result == {
        "error": "missing_parameter",
        "message": "Missing required parameter: 'session_id'.",
    }


async def test_session_not_found(mock_runtime):
    mock_runtime.get_session.return_value = None
    result = await search_semantic(mock_runtime, {"session_id": "missing", "query": "fruit"})
    assert result == {
        "error": "session_not_found",
        "message": "Session 'missing' not found.",
    }


@pytest.mark.parametrize("query", ["", "   ", "\t\n"])
async def test_empty_or_whitespace_query_rejected(mock_runtime, query):
    result = await search_semantic(mock_runtime, {"session_id": "s1", "query": query})
    assert result == {
        "error": "empty_query",
        "message": "Query must not be empty.",
    }


async def test_empty_query_does_not_attempt_vector_search(mock_runtime):
    runtime = MagicMock()
    runtime.get_session.return_value = MagicMock(session_id="s1")
    await search_semantic(runtime, {"session_id": "s1", "query": ""})
    runtime.embedding_client.embed_batch.assert_not_called()


async def test_no_seed_ids_and_no_vector_search_support_returns_not_found(mock_runtime):
    result = await search_semantic(mock_runtime, {"session_id": "s1", "query": "fruit"})
    assert result["error"] == "not_found"


async def test_vector_search_exception_message_is_surfaced(mock_runtime):
    mock_runtime.storage.search_embeddings = AsyncMock(
        side_effect=RuntimeError("HF_TOKEN invalid or expired")
    )
    mock_runtime.embedding_client.embed_batch.return_value = [b"\x00" * 16]
    result = await search_semantic(mock_runtime, {"session_id": "s1", "query": "fruit"})
    assert result["error"] == "not_found"
    assert "HF_TOKEN invalid or expired" in result["message"]


async def test_explicit_seed_ids_skip_vector_search_and_have_no_scores(mock_runtime):
    mock_runtime.storage.search_embeddings = AsyncMock()
    with_seed_ids = {"session_id": "s1", "query": "fruit", "seed_ids": ["obj-1"]}
    import cks_mcp.tools.search_semantic.handler as mod
    orig = mod.query_subgraph_tool
    mod.query_subgraph_tool = AsyncMock(return_value={
        "subgraph": {}, "total_found_nodes": 1, "returned_nodes": 1,
        "is_truncated": False, "suggested_next_seed": None,
    })
    try:
        result = await search_semantic(mock_runtime, with_seed_ids)
    finally:
        mod.query_subgraph_tool = orig

    assert "scores" not in result
    mock_runtime.storage.search_embeddings.assert_not_called()


# ---------------------------------------------------------------------------
# Real end-to-end vector search (SQLiteStorage + StubEmbeddingClient)
# ---------------------------------------------------------------------------

async def _make_indexed_session(tmp_path):
    config = RuntimeConfig(storage_path=str(tmp_path / "search_semantic_test.db"))
    runtime = Runtime(core=CksCoreAdapter(), config=config)

    ks = cks.parse(
        '{"objects":['
        '{"identity":{"id":"obj-1","type":"Test","name":"apple"},'
        '"structure":{"description":"a red fruit"}},'
        '{"identity":{"id":"obj-2","type":"Test","name":"car"},'
        '"structure":{"description":"a vehicle with wheels"}}'
        ']}'
    )
    session = await runtime.create_session(ks)
    tx = runtime.begin_transaction(session)
    tx.add_operation(ValidateOperation("v1", knowledge_structure=ks))
    await runtime.commit_transaction(tx)

    deadline = time.time() + 5
    while time.time() < deadline:
        rows = runtime.storage._conn.execute(
            "SELECT object_id FROM cks_object_embeddings"
        ).fetchall()
        if len(rows) >= 2:
            break
        await asyncio.sleep(0.05)
    return runtime, session


@pytest.mark.skip(reason="Requires direct SQLite connection")
async def test_real_vector_search_returns_scores_for_matched_seeds(tmp_path):
    runtime, session = await _make_indexed_session(tmp_path)

    result = await search_semantic(runtime, {"session_id": session.session_id, "query": "fruit"})

    assert result["status"] == "success"
    assert "scores" in result
    assert set(result["scores"].keys()) == set(result["matched_seeds"])
    for score in result["scores"].values():
        assert 0.0 <= score <= 1.0


@pytest.mark.skip(reason="Requires direct SQLite connection")
async def test_real_explicit_seed_ids_have_no_scores_field(tmp_path):
    runtime, session = await _make_indexed_session(tmp_path)

    result = await search_semantic(
        runtime,
        {"session_id": session.session_id, "query": "fruit", "seed_ids": ["obj-1"]},
    )

    assert result["status"] == "success"
    assert "scores" not in result


@pytest.mark.skip(reason="Requires direct SQLite connection")
async def test_query_subgraph_error_is_passed_through(tmp_path, monkeypatch):
    runtime, session = await _make_indexed_session(tmp_path)

    import cks_mcp.tools.search_semantic.handler as mod
    monkeypatch.setattr(
        mod, "query_subgraph_tool",
        MagicMock(return_value={"error": "query_subgraph failed: boom"}),
    )

    result = await search_semantic(
        runtime,
        {"session_id": session.session_id, "query": "fruit", "seed_ids": ["obj-1"]},
    )
    assert result == {"error": "query_subgraph failed: boom"}