"""Unit tests for cks_mcp.pipeline.synthesizer_step."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.pipeline.schema import PipelineStatus
from cks_mcp.pipeline.synthesizer_step import (
    SynthesizerStepSettings,
    _objects_content_hash,
    resolve_pipeline_synthesis_request,
)

pytestmark = pytest.mark.asyncio


def _make_obj(object_id="obj-1", name="Widget", obj_type="Concept", structure=None):
    return SimpleNamespace(
        identity=SimpleNamespace(id=object_id, name=name, type=obj_type),
        structure=structure or {},
    )


def _make_session(objects):
    return SimpleNamespace(knowledge_structure=SimpleNamespace(objects=objects))


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.enqueue_task = AsyncMock()
    return runtime


def _valid_llm_json() -> str:
    return json.dumps(
        {
            "objects": [
                {
                    "id": "fact-1",
                    "type": "Claim",
                    "name": "Synthesized fact",
                    "structure": {"content": "deduplicated fact"},
                }
            ]
        }
    )


async def test_missing_object_ids_fails(mock_runtime):
    task = {"session_id": "s1", "payload": {}}
    resolution = await resolve_pipeline_synthesis_request(
        mock_runtime, task, SynthesizerStepSettings(storage_path=":memory:")
    )
    assert resolution.resolved is False
    assert "object_ids" in resolution.detail


async def test_session_not_found_fails(mock_runtime):
    mock_runtime.get_session = MagicMock(return_value=None)
    task = {"session_id": "s1", "payload": {"object_ids": ["obj-1"]}}
    resolution = await resolve_pipeline_synthesis_request(
        mock_runtime, task, SynthesizerStepSettings(storage_path=":memory:")
    )
    assert resolution.resolved is False
    assert "session" in resolution.detail


async def test_missing_source_object_fails(mock_runtime):
    mock_runtime.get_session = MagicMock(return_value=_make_session([]))
    task = {"session_id": "s1", "payload": {"object_ids": ["obj-1"]}}
    resolution = await resolve_pipeline_synthesis_request(
        mock_runtime, task, SynthesizerStepSettings(storage_path=":memory:")
    )
    assert resolution.resolved is False
    assert "not found" in resolution.detail


async def test_successful_synthesis_evolves_and_enqueues_review(mock_runtime, monkeypatch):
    obj_a = _make_obj(object_id="obj-1", structure={"content": "fact A"})
    obj_b = _make_obj(object_id="obj-2", structure={"content": "fact B"})
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj_a, obj_b]))

    async def _fake_query_subgraph(runtime, arguments):
        assert arguments["session_id"] == "s1"
        assert arguments["seed_ids"] == ["obj-1", "obj-2"]
        return {"session_id": "s1", "returned_nodes": 2}

    monkeypatch.setattr(
        "cks_mcp.pipeline.synthesizer_step.query_subgraph_tool", _fake_query_subgraph
    )

    captured_ops: list[dict] = []

    async def _fake_evolve(runtime, arguments):
        assert arguments["session_id"] == "s1"
        captured_ops.extend(arguments["operations"])
        return {"session_id": "s1"}

    monkeypatch.setattr("cks_mcp.pipeline.synthesizer_step.evolve_knowledge", _fake_evolve)
    monkeypatch.setattr(
        "cks_mcp.pipeline.synthesizer_step.call_llm",
        lambda prompt, *, system_prompt=None, tool_name=None, model, max_tokens: (
            _valid_llm_json(),
            "test-model",
        ),
    )

    task = {"session_id": "s1", "payload": {"object_ids": ["obj-1", "obj-2"]}}
    resolution = await resolve_pipeline_synthesis_request(
        mock_runtime, task, SynthesizerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    assert resolution.detail == PipelineStatus.AWAITING_REVIEW

    op_types = [op["type"] for op in captured_ops]
    assert op_types.count("add_object") == 1
    assert op_types.count("add_relation") == 2  # one per source object
    assert op_types.count("update_object") == 2  # one transition per source object

    mock_runtime.storage.enqueue_task.assert_awaited_once()
    _, kwargs = mock_runtime.storage.enqueue_task.call_args
    assert kwargs["task_type"] == "pipeline_review_request"
    enqueued_payload = json.loads(kwargs["payload"])
    assert enqueued_payload["source_object_ids"] == ["obj-1", "obj-2"]


async def test_idempotent_skips_llm_when_already_synthesized(mock_runtime, monkeypatch):
    obj_a = _make_obj(object_id="obj-1", structure={"content": "fact A"})
    obj_b = _make_obj(object_id="obj-2", structure={"content": "fact B"})

    content_hash = _objects_content_hash([obj_a, obj_b])
    obj_a.structure["transition_log"] = [
        {
            "agent": "SynthesizerAgent",
            "content_hash": content_hash,
            "transitioned_to": "awaiting_review",
            "reasoning_node_id": "synthesis-obj-1-obj-2-abc123",
        }
    ]

    mock_runtime.get_session = MagicMock(return_value=_make_session([obj_a, obj_b]))

    def _boom(*args, **kwargs):
        raise AssertionError("LLM should not be called when already synthesized")

    monkeypatch.setattr("cks_mcp.pipeline.synthesizer_step.call_llm", _boom)

    task = {"session_id": "s1", "payload": {"object_ids": ["obj-1", "obj-2"]}}
    resolution = await resolve_pipeline_synthesis_request(
        mock_runtime, task, SynthesizerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    assert resolution.detail == PipelineStatus.AWAITING_REVIEW
    # Regression: the idempotent-skip path must still enqueue the
    # review task -- otherwise a retry after "evolve_knowledge
    # committed but enqueue_task crashed" strands the synthesized node
    # with no task in any outbox queue.
    mock_runtime.storage.enqueue_task.assert_awaited_once()
    _, kwargs = mock_runtime.storage.enqueue_task.call_args
    assert kwargs["task_type"] == "pipeline_review_request"
    assert json.loads(kwargs["payload"])["object_id"] == "synthesis-obj-1-obj-2-abc123"


async def test_llm_failure_returns_unresolved(mock_runtime, monkeypatch):
    obj_a = _make_obj(object_id="obj-1")
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj_a]))

    async def _fake_query_subgraph(runtime, arguments):
        return {"session_id": "s1"}

    monkeypatch.setattr(
        "cks_mcp.pipeline.synthesizer_step.query_subgraph_tool", _fake_query_subgraph
    )

    def _raise(*args, **kwargs):
        raise RuntimeError("no provider available")

    monkeypatch.setattr("cks_mcp.pipeline.synthesizer_step.call_llm", _raise)

    task = {"session_id": "s1", "payload": {"object_ids": ["obj-1"]}}
    resolution = await resolve_pipeline_synthesis_request(
        mock_runtime, task, SynthesizerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is False
    assert "LLM call failed" in resolution.detail


async def test_invalid_json_response_returns_unresolved(mock_runtime, monkeypatch):
    obj_a = _make_obj(object_id="obj-1")
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj_a]))

    async def _fake_query_subgraph(runtime, arguments):
        return {"session_id": "s1"}

    monkeypatch.setattr(
        "cks_mcp.pipeline.synthesizer_step.query_subgraph_tool", _fake_query_subgraph
    )
    monkeypatch.setattr(
        "cks_mcp.pipeline.synthesizer_step.call_llm",
        lambda prompt, *, system_prompt=None, tool_name=None, model, max_tokens: (
            "not json at all",
            "test-model",
        ),
    )

    task = {"session_id": "s1", "payload": {"object_ids": ["obj-1"]}}
    resolution = await resolve_pipeline_synthesis_request(
        mock_runtime, task, SynthesizerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is False
    assert "failed to parse synthesis response" in resolution.detail


async def test_query_subgraph_error_returns_unresolved(mock_runtime, monkeypatch):
    obj_a = _make_obj(object_id="obj-1")
    mock_runtime.get_session = MagicMock(return_value=_make_session([obj_a]))

    async def _fake_query_subgraph(runtime, arguments):
        return {"error": "boom"}

    monkeypatch.setattr(
        "cks_mcp.pipeline.synthesizer_step.query_subgraph_tool", _fake_query_subgraph
    )

    task = {"session_id": "s1", "payload": {"object_ids": ["obj-1"]}}
    resolution = await resolve_pipeline_synthesis_request(
        mock_runtime, task, SynthesizerStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is False
    assert "query_subgraph failed" in resolution.detail
