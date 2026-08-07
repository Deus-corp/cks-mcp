"""Unit tests for cks_mcp.pipeline.reviewer_step."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

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
    return MagicMock()


async def test_missing_object_id_fails(mock_runtime):
    task = {"session_id": "s1", "payload": {}}
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )
    assert resolution.resolved is False


async def test_object_not_found_fails(mock_runtime):
    mock_runtime.get_session = MagicMock(return_value=_make_session([]))
    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )
    assert resolution.resolved is False


async def test_approve_moves_to_resolved(mock_runtime, monkeypatch):
    obj = _make_obj()
    finding = _make_obj(object_id="finding-1", structure={"content": "some finding"})
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj, finding]))

    async def _fake_evolve(runtime, arguments):
        ops = arguments["operations"]
        last = ops[-1]
        assert last["structure_patch"]["current_status"] == PipelineStatus.RESOLVED
        return {"session_id": "s1"}

    monkeypatch.setattr("cks_mcp.pipeline.reviewer_step.evolve_knowledge", _fake_evolve)
    monkeypatch.setattr(
        "cks_mcp.pipeline.reviewer_step._call_llm",
        lambda prompt, *, model, max_tokens: ("APPROVE: looks solid", "test-model"),
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


async def test_reject_moves_to_needs_research(mock_runtime, monkeypatch):
    obj = _make_obj()
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj]))

    async def _fake_evolve(runtime, arguments):
        return {"session_id": "s1"}

    monkeypatch.setattr("cks_mcp.pipeline.reviewer_step.evolve_knowledge", _fake_evolve)
    monkeypatch.setattr(
        "cks_mcp.pipeline.reviewer_step._call_llm",
        lambda prompt, *, model, max_tokens: ("REJECT: not supported", "test-model"),
    )

    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    assert resolution.detail == PipelineStatus.NEEDS_RESEARCH


async def test_unparseable_verdict_treated_as_reject(mock_runtime, monkeypatch):
    obj = _make_obj()
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj]))

    async def _fake_evolve(runtime, arguments):
        return {"session_id": "s1"}

    monkeypatch.setattr("cks_mcp.pipeline.reviewer_step.evolve_knowledge", _fake_evolve)
    monkeypatch.setattr(
        "cks_mcp.pipeline.reviewer_step._call_llm",
        lambda prompt, *, model, max_tokens: ("uh, I dunno", "test-model"),
    )

    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )

    assert resolution.detail == PipelineStatus.NEEDS_RESEARCH


async def test_idempotent_skips_llm_and_returns_prior_outcome(mock_runtime, monkeypatch):
    content_hash = hashlib.sha256(json.dumps({}, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    structure = {
        "transition_log": [
            {"agent": "ReviewerAgent", "content_hash": content_hash, "transitioned_to": PipelineStatus.RESOLVED}
        ]
    }
    obj = _make_obj(structure=structure)
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj]))

    def _boom(*args, **kwargs):
        raise AssertionError("LLM should not be called when already reviewed")

    monkeypatch.setattr("cks_mcp.pipeline.reviewer_step._call_llm", _boom)

    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    assert resolution.detail == PipelineStatus.RESOLVED


async def test_llm_failure_returns_unresolved(mock_runtime, monkeypatch):
    obj = _make_obj()
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj]))

    def _raise(*args, **kwargs):
        raise RuntimeError("no provider available")

    monkeypatch.setattr("cks_mcp.pipeline.reviewer_step._call_llm", _raise)

    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_pipeline_review_request(
        mock_runtime, task, ReviewerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is False