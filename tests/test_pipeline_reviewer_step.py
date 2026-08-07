"""Unit tests for cks_mcp.pipeline.reviewer_step."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.pipeline.reviewer_step import (
    ReviewerStepSettings,
    resolve_pipeline_review_request,
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
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )
    assert resolution.resolved is False
    assert "object_id" in resolution.detail


async def test_session_not_found_fails(mock_runtime):
    mock_runtime.get_session = MagicMock(return_value=None)
    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )
    assert resolution.resolved is False
    assert "session" in resolution.detail


async def test_object_not_found_fails(mock_runtime):
    mock_runtime.get_session = MagicMock(return_value=_make_session([]))
    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )
    assert resolution.resolved is False
    assert "not found" in resolution.detail


async def test_approve(mock_runtime, monkeypatch):
    obj = _make_obj()
    finding = _make_obj(object_id="finding-1", structure={"content": "some finding"})
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj, finding]))

    async def _fake_evolve(runtime, arguments):
        return {"session_id": "s1"}

    monkeypatch.setattr(
        "cks_mcp.pipeline.reviewer_step.evolve_knowledge", _fake_evolve
    )
    monkeypatch.setattr(
        "cks_mcp.pipeline.reviewer_step.call_llm",
        lambda prompt, *, system_prompt=None, tool_name=None, model, max_tokens: ("APPROVE: looks solid", "test-model"),
    )

    task = {
        "session_id": "s1",
        "payload": {"object_id": "obj-1", "reasoning_node_id": "finding-1"},
    }
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    assert resolution.detail == PipelineStatus.RESOLVED
    mock_runtime.storage.enqueue_task.assert_not_awaited()


async def test_reject_moves_to_needs_research(mock_runtime, monkeypatch):
    obj = _make_obj()
    finding = _make_obj(object_id="finding-1", structure={"content": "some finding"})
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj, finding]))

    async def _fake_evolve(runtime, arguments):
        return {"session_id": "s1"}

    monkeypatch.setattr(
        "cks_mcp.pipeline.reviewer_step.evolve_knowledge", _fake_evolve
    )
    monkeypatch.setattr(
        "cks_mcp.pipeline.reviewer_step.call_llm",
        lambda prompt, *, system_prompt=None, tool_name=None, model, max_tokens: ("REJECT: not supported", "test-model"),
    )

    task = {
        "session_id": "s1",
        "payload": {"object_id": "obj-1", "reasoning_node_id": "finding-1"},
    }
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    assert resolution.detail == PipelineStatus.NEEDS_RESEARCH
    mock_runtime.storage.enqueue_task.assert_awaited_once()
    _, kwargs = mock_runtime.storage.enqueue_task.call_args
    assert kwargs["task_type"] == "pipeline_research_request"
    assert json.loads(kwargs["payload"])["object_id"] == "obj-1"


async def test_approve_does_not_requeue_researcher(mock_runtime, monkeypatch):
    obj = _make_obj()
    finding = _make_obj(object_id="finding-1", structure={"content": "some finding"})
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj, finding]))

    async def _fake_evolve(runtime, arguments):
        return {"session_id": "s1"}

    monkeypatch.setattr(
        "cks_mcp.pipeline.reviewer_step.evolve_knowledge", _fake_evolve
    )
    monkeypatch.setattr(
        "cks_mcp.pipeline.reviewer_step.call_llm",
        lambda prompt, *, system_prompt=None, tool_name=None, model, max_tokens: ("APPROVE: looks solid", "test-model"),
    )

    task = {
        "session_id": "s1",
        "payload": {"object_id": "obj-1", "reasoning_node_id": "finding-1"},
    }
    await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )

    # RESOLVED is a terminal Milestone-1 status -- nothing to enqueue.
    mock_runtime.storage.enqueue_task.assert_not_awaited()


async def test_unparseable_verdict_treated_as_reject(mock_runtime, monkeypatch):
    obj = _make_obj()
    finding = _make_obj(object_id="finding-1", structure={"content": "some finding"})
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj, finding]))

    async def _fake_evolve(runtime, arguments):
        return {"session_id": "s1"}

    monkeypatch.setattr(
        "cks_mcp.pipeline.reviewer_step.evolve_knowledge", _fake_evolve
    )
    monkeypatch.setattr(
        "cks_mcp.pipeline.reviewer_step.call_llm",
        lambda prompt, *, system_prompt=None, tool_name=None, model, max_tokens: ("uh, I dunno", "test-model"),
    )

    task = {
        "session_id": "s1",
        "payload": {"object_id": "obj-1", "reasoning_node_id": "finding-1"},
    }
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    # unparseable verdict defaults to rejection
    assert resolution.detail == PipelineStatus.NEEDS_RESEARCH


async def test_idempotent_skips_llm_and_returns_prior_outcome(mock_runtime, monkeypatch):
    import hashlib

    content_hash = hashlib.sha256(
        json.dumps({}, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    structure = {
        "transition_log": [
            {
                "agent": "ReviewerAgent",
                "content_hash": content_hash,
                "transitioned_to": PipelineStatus.RESOLVED,
            }
        ]
    }
    obj = _make_obj(structure=structure)
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj]))

    def _boom(*args, **kwargs):
        raise AssertionError("LLM should not be called when already reviewed")

    monkeypatch.setattr("cks_mcp.pipeline.reviewer_step.call_llm", _boom)

    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    assert resolution.detail == PipelineStatus.RESOLVED
    # Prior outcome was RESOLVED -- terminal, nothing to re-enqueue.
    mock_runtime.storage.enqueue_task.assert_not_awaited()


async def test_idempotent_skip_reenqueues_research_when_prior_outcome_was_reject(
    mock_runtime, monkeypatch
):
    import hashlib

    content_hash = hashlib.sha256(
        json.dumps({}, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    structure = {
        "transition_log": [
            {
                "agent": "ReviewerAgent",
                "content_hash": content_hash,
                "transitioned_to": PipelineStatus.NEEDS_RESEARCH,
            }
        ]
    }
    obj = _make_obj(structure=structure)
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj]))

    def _boom(*args, **kwargs):
        raise AssertionError("LLM should not be called when already reviewed")

    monkeypatch.setattr("cks_mcp.pipeline.reviewer_step.call_llm", _boom)

    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    assert resolution.detail == PipelineStatus.NEEDS_RESEARCH
    mock_runtime.storage.enqueue_task.assert_awaited_once()
    _, kwargs = mock_runtime.storage.enqueue_task.call_args
    assert kwargs["task_type"] == "pipeline_research_request"


async def test_llm_failure_returns_unresolved(mock_runtime, monkeypatch):
    obj = _make_obj()
    finding = _make_obj(object_id="finding-1", structure={"content": "some finding"})
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj, finding]))

    def _raise(*args, **kwargs):
        raise RuntimeError("no provider available")

    monkeypatch.setattr("cks_mcp.pipeline.reviewer_step.call_llm", _raise)

    task = {
        "session_id": "s1",
        "payload": {"object_id": "obj-1", "reasoning_node_id": "finding-1"},
    }
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is False
    assert "LLM call failed" in resolution.detail