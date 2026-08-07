"""Unit tests for cks_mcp.pipeline.researcher_step."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.pipeline.researcher_step import (
    ResearcherStepSettings,
    resolve_pipeline_research_request,
)
from cks_mcp.pipeline.schema import PipelineStatus

pytestmark = pytest.mark.asyncio


def _make_obj(object_id="obj-1", name="Widget", structure=None):
    return SimpleNamespace(
        identity=SimpleNamespace(id=object_id, name=name, type="Concept"),
        structure=structure or {},
    )


def _make_session(objects):
    return SimpleNamespace(knowledge_structure=SimpleNamespace(objects=objects))


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.enqueue_task = AsyncMock()
    return runtime


async def test_missing_object_id_fails(mock_runtime):
    task = {"session_id": "s1", "payload": {}}
    resolution = await resolve_pipeline_research_request(
        mock_runtime, task, ResearcherStepSettings(storage_path=":memory:")
    )
    assert resolution.resolved is False
    assert "object_id" in resolution.detail


async def test_session_not_found_fails(mock_runtime):
    mock_runtime.get_session = MagicMock(return_value=None)
    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_research_request(
        mock_runtime, task, ResearcherStepSettings(storage_path=":memory:")
    )
    assert resolution.resolved is False
    assert "session" in resolution.detail


async def test_object_not_found_fails(mock_runtime):
    mock_runtime.get_session = MagicMock(return_value=_make_session([]))
    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_research_request(
        mock_runtime, task, ResearcherStepSettings(storage_path=":memory:")
    )
    assert resolution.resolved is False
    assert "not found" in resolution.detail


async def test_successful_research_evolves_and_enqueues_review(mock_runtime, monkeypatch):
    obj = _make_obj()
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj]))

    async def _fake_evolve(runtime, arguments):
        assert arguments["session_id"] == "s1"
        ops = arguments["operations"]
        types = [op["type"] for op in ops]
        assert types == ["add_object", "add_relation", "update_object"]
        return {"session_id": "s1"}

    monkeypatch.setattr(
        "cks_mcp.pipeline.researcher_step.evolve_knowledge", _fake_evolve
    )
    monkeypatch.setattr(
        "cks_mcp.pipeline.researcher_step._call_llm",
        lambda prompt, *, model, max_tokens: ("Some finding text", "test-model"),
    )

    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_research_request(
        mock_runtime, task, ResearcherStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    assert resolution.detail == PipelineStatus.AWAITING_REVIEW
    mock_runtime.storage.enqueue_task.assert_awaited_once()
    _, kwargs = mock_runtime.storage.enqueue_task.call_args
    assert kwargs["task_type"] == "pipeline_review_request"


async def test_idempotent_skips_llm_when_already_researched(mock_runtime, monkeypatch):
    import hashlib
    import json

    content_hash = hashlib.sha256(
        json.dumps({}, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    structure = {
        "transition_log": [
            {"agent": "ResearcherAgent", "content_hash": content_hash, "transitioned_to": "awaiting_review"}
        ]
    }
    obj = _make_obj(structure=structure)
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj]))

    def _boom(*args, **kwargs):
        raise AssertionError("LLM should not be called when already researched")

    monkeypatch.setattr("cks_mcp.pipeline.researcher_step._call_llm", _boom)

    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_research_request(
        mock_runtime, task, ResearcherStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    # Regression: the idempotent-skip path must still enqueue the
    # review task -- otherwise a retry after "evolve_knowledge
    # committed but enqueue_task crashed" strands the object with no
    # task in any outbox queue.
    mock_runtime.storage.enqueue_task.assert_awaited_once()
    _, kwargs = mock_runtime.storage.enqueue_task.call_args
    assert kwargs["task_type"] == "pipeline_review_request"
    assert json.loads(kwargs["payload"])["object_id"] == "obj-1"


async def test_llm_failure_returns_unresolved(mock_runtime, monkeypatch):
    obj = _make_obj()
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj]))

    def _raise(*args, **kwargs):
        raise RuntimeError("no provider available")

    monkeypatch.setattr("cks_mcp.pipeline.researcher_step._call_llm", _raise)

    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_research_request(
        mock_runtime, task, ResearcherStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is False
    assert "LLM call failed" in resolution.detail