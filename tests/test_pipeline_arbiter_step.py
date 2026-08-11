"""Unit tests for cks_mcp.pipeline.arbiter_step."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cks_mcp.pipeline.arbiter_step import (
    ArbiterStepSettings,
    _contradiction_content_hash,
    resolve_pipeline_arbitration_request,
)
from cks_mcp.pipeline.schema import PipelineStatus

pytestmark = pytest.mark.asyncio


def _make_relation(rel_id, participants, relation_type="contradicts", structure=None):
    return SimpleNamespace(
        identity=SimpleNamespace(id=rel_id, name=rel_id, type="Relation"),
        participants=participants,
        relation_type=relation_type,
        structure=structure or {},
    )


def _make_claim(claim_id, structure=None):
    return SimpleNamespace(
        identity=SimpleNamespace(id=claim_id, name=claim_id, type="Claim"),
        structure=structure or {},
    )


def _make_session():
    # find_object is monkeypatched per-test, so the session itself only
    # needs to exist / be truthy.
    return SimpleNamespace(knowledge_structure=SimpleNamespace())


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    return runtime


def _listing_result(location="rel-a", code="CKS-EXT-MUTUAL-EXCLUSION", relation_ids=None):
    relation_ids = relation_ids or ["rel-a", "rel-b"]
    return {
        "session_id": "s1",
        "contradiction_count": 1,
        "contradictions": [
            {
                "id": location,
                "code": code,
                "severity": "error",
                "message": "conflict",
                "relation_ids": sorted(relation_ids),
            }
        ],
    }


def _valid_decision_json(winner_relation_id="rel-a"):
    return json.dumps({"winner_relation_id": winner_relation_id, "reason": "more reliable source"})


async def test_missing_location_fails(mock_runtime):
    task = {"session_id": "s1", "payload": {}}
    resolution = await resolve_pipeline_arbitration_request(
        mock_runtime, task, ArbiterStepSettings(storage_path=":memory:")
    )
    assert resolution.resolved is False
    assert "location" in resolution.detail


async def test_session_not_found_fails(mock_runtime):
    mock_runtime.get_session = MagicMock(return_value=None)
    task = {"session_id": "s1", "payload": {"location": "rel-a", "code": "X"}}
    resolution = await resolve_pipeline_arbitration_request(
        mock_runtime, task, ArbiterStepSettings(storage_path=":memory:")
    )
    assert resolution.resolved is False
    assert "session" in resolution.detail


async def test_already_resolved_contradiction_is_a_noop(mock_runtime, monkeypatch):
    mock_runtime.get_session = MagicMock(return_value=_make_session())

    async def _fake_listing(runtime, arguments):
        return {"session_id": "s1", "contradiction_count": 0, "contradictions": []}

    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.resolve_contradiction_tool", _fake_listing
    )

    def _boom(*args, **kwargs):
        raise AssertionError("LLM should not be called when contradiction is already gone")

    monkeypatch.setattr("cks_mcp.pipeline.arbiter_step.call_llm", _boom)

    task = {"session_id": "s1", "payload": {"location": "rel-a", "code": "X"}}
    resolution = await resolve_pipeline_arbitration_request(
        mock_runtime, task, ArbiterStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    assert resolution.detail == PipelineStatus.RESOLVED


async def test_successful_arbitration_removes_loser_and_records_verdict(mock_runtime, monkeypatch):
    mock_runtime.get_session = MagicMock(return_value=_make_session())

    rel_a = _make_relation("rel-a", ["claim-x", "claim-y"])
    rel_b = _make_relation("rel-b", ["claim-x", "claim-y"])
    claim_x = _make_claim("claim-x", structure={"confidence": 0.9, "source": "trusted"})
    claim_y = _make_claim("claim-y", structure={"confidence": 0.4, "source": "unverified"})

    objects_by_id = {
        "rel-a": rel_a,
        "rel-b": rel_b,
        "claim-x": claim_x,
        "claim-y": claim_y,
    }

    def _fake_find_object(session, object_id):
        return objects_by_id.get(object_id)

    monkeypatch.setattr("cks_mcp.pipeline.arbiter_step.find_object", _fake_find_object)

    async def _fake_listing(runtime, arguments):
        return _listing_result()

    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.resolve_contradiction_tool", _fake_listing
    )

    async def _fake_query_subgraph(runtime, arguments):
        assert arguments["seed_ids"] == ["claim-x", "claim-y"]
        assert arguments["compact_mode"] is True
        return {"session_id": "s1", "subgraph": {"nodes": [], "edges": []}}

    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.query_subgraph_tool", _fake_query_subgraph
    )

    captured_ops: list[dict] = []

    async def _fake_evolve(runtime, arguments):
        assert arguments["session_id"] == "s1"
        captured_ops.extend(arguments["operations"])
        return {"session_id": "s1"}

    monkeypatch.setattr("cks_mcp.pipeline.arbiter_step.evolve_knowledge", _fake_evolve)
    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.call_llm",
        lambda prompt, *, system_prompt=None, tool_name=None, model, max_tokens: (
            _valid_decision_json(winner_relation_id="rel-a"),
            "test-model",
        ),
    )

    task = {
        "session_id": "s1",
        "payload": {"location": "rel-a", "code": "CKS-EXT-MUTUAL-EXCLUSION"},
    }
    resolution = await resolve_pipeline_arbitration_request(
        mock_runtime, task, ArbiterStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    assert resolution.detail == PipelineStatus.RESOLVED

    remove_ops = [op for op in captured_ops if op["type"] == "remove_relation"]
    assert [op["relation_id"] for op in remove_ops] == ["rel-b"]

    add_object_ops = [op for op in captured_ops if op["type"] == "add_object"]
    assert len(add_object_ops) == 1
    assert add_object_ops[0]["structure"]["winner_relation_id"] == "rel-a"
    assert add_object_ops[0]["structure"]["removed_relation_ids"] == ["rel-b"]

    update_ops = [op for op in captured_ops if op["type"] == "update_object"]
    assert {op["object_id"] for op in update_ops} == {"claim-x", "claim-y"}


async def test_idempotent_skips_llm_when_already_arbitrated(mock_runtime, monkeypatch):
    mock_runtime.get_session = MagicMock(return_value=_make_session())

    rel_a = _make_relation("rel-a", ["claim-x", "claim-y"])
    rel_b = _make_relation("rel-b", ["claim-x", "claim-y"])

    content_hash = _contradiction_content_hash(
        "rel-a", "CKS-EXT-MUTUAL-EXCLUSION", ["rel-a", "rel-b"]
    )
    claim_x = _make_claim(
        "claim-x",
        structure={
            "transition_log": [
                {
                    "agent": "ArbiterAgent",
                    "content_hash": content_hash,
                    "transitioned_to": "resolved",
                    "reasoning_node_id": "arbitration-rel-a-abc123",
                }
            ]
        },
    )
    claim_y = _make_claim("claim-y")

    objects_by_id = {
        "rel-a": rel_a,
        "rel-b": rel_b,
        "claim-x": claim_x,
        "claim-y": claim_y,
    }

    def _fake_find_object(session, object_id):
        return objects_by_id.get(object_id)

    monkeypatch.setattr("cks_mcp.pipeline.arbiter_step.find_object", _fake_find_object)

    async def _fake_listing(runtime, arguments):
        return _listing_result()

    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.resolve_contradiction_tool", _fake_listing
    )

    def _boom(*args, **kwargs):
        raise AssertionError("LLM should not be called when already arbitrated")

    monkeypatch.setattr("cks_mcp.pipeline.arbiter_step.call_llm", _boom)

    task = {
        "session_id": "s1",
        "payload": {"location": "rel-a", "code": "CKS-EXT-MUTUAL-EXCLUSION"},
    }
    resolution = await resolve_pipeline_arbitration_request(
        mock_runtime, task, ArbiterStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is True
    assert resolution.detail == PipelineStatus.RESOLVED


async def test_llm_failure_returns_unresolved(mock_runtime, monkeypatch):
    mock_runtime.get_session = MagicMock(return_value=_make_session())

    rel_a = _make_relation("rel-a", ["claim-x"])
    rel_b = _make_relation("rel-b", ["claim-x"])
    claim_x = _make_claim("claim-x")

    objects_by_id = {"rel-a": rel_a, "rel-b": rel_b, "claim-x": claim_x}
    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.find_object",
        lambda session, oid: objects_by_id.get(oid),
    )

    async def _fake_listing(runtime, arguments):
        return _listing_result(relation_ids=["rel-a", "rel-b"])

    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.resolve_contradiction_tool", _fake_listing
    )

    async def _fake_query_subgraph(runtime, arguments):
        return {"session_id": "s1", "subgraph": {"nodes": [], "edges": []}}

    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.query_subgraph_tool", _fake_query_subgraph
    )

    def _raise(*args, **kwargs):
        raise RuntimeError("no provider available")

    monkeypatch.setattr("cks_mcp.pipeline.arbiter_step.call_llm", _raise)

    task = {
        "session_id": "s1",
        "payload": {"location": "rel-a", "code": "CKS-EXT-MUTUAL-EXCLUSION"},
    }
    resolution = await resolve_pipeline_arbitration_request(
        mock_runtime, task, ArbiterStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is False
    assert "LLM call failed" in resolution.detail


async def test_invalid_json_response_returns_unresolved(mock_runtime, monkeypatch):
    mock_runtime.get_session = MagicMock(return_value=_make_session())

    rel_a = _make_relation("rel-a", ["claim-x"])
    rel_b = _make_relation("rel-b", ["claim-x"])
    claim_x = _make_claim("claim-x")

    objects_by_id = {"rel-a": rel_a, "rel-b": rel_b, "claim-x": claim_x}
    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.find_object",
        lambda session, oid: objects_by_id.get(oid),
    )

    async def _fake_listing(runtime, arguments):
        return _listing_result(relation_ids=["rel-a", "rel-b"])

    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.resolve_contradiction_tool", _fake_listing
    )

    async def _fake_query_subgraph(runtime, arguments):
        return {"session_id": "s1", "subgraph": {"nodes": [], "edges": []}}

    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.query_subgraph_tool", _fake_query_subgraph
    )
    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.call_llm",
        lambda prompt, *, system_prompt=None, tool_name=None, model, max_tokens: (
            "not json at all",
            "test-model",
        ),
    )

    task = {
        "session_id": "s1",
        "payload": {"location": "rel-a", "code": "CKS-EXT-MUTUAL-EXCLUSION"},
    }
    resolution = await resolve_pipeline_arbitration_request(
        mock_runtime, task, ArbiterStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is False
    assert "failed to parse arbitration response" in resolution.detail


async def test_hallucinated_winner_id_returns_unresolved(mock_runtime, monkeypatch):
    mock_runtime.get_session = MagicMock(return_value=_make_session())

    rel_a = _make_relation("rel-a", ["claim-x"])
    rel_b = _make_relation("rel-b", ["claim-x"])
    claim_x = _make_claim("claim-x")

    objects_by_id = {"rel-a": rel_a, "rel-b": rel_b, "claim-x": claim_x}
    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.find_object",
        lambda session, oid: objects_by_id.get(oid),
    )

    async def _fake_listing(runtime, arguments):
        return _listing_result(relation_ids=["rel-a", "rel-b"])

    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.resolve_contradiction_tool", _fake_listing
    )

    async def _fake_query_subgraph(runtime, arguments):
        return {"session_id": "s1", "subgraph": {"nodes": [], "edges": []}}

    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.query_subgraph_tool", _fake_query_subgraph
    )
    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.call_llm",
        lambda prompt, *, system_prompt=None, tool_name=None, model, max_tokens: (
            _valid_decision_json(winner_relation_id="rel-does-not-exist"),
            "test-model",
        ),
    )

    task = {
        "session_id": "s1",
        "payload": {"location": "rel-a", "code": "CKS-EXT-MUTUAL-EXCLUSION"},
    }
    resolution = await resolve_pipeline_arbitration_request(
        mock_runtime, task, ArbiterStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is False
    assert "failed to parse arbitration response" in resolution.detail


async def test_query_subgraph_error_returns_unresolved(mock_runtime, monkeypatch):
    mock_runtime.get_session = MagicMock(return_value=_make_session())

    rel_a = _make_relation("rel-a", ["claim-x"])
    rel_b = _make_relation("rel-b", ["claim-x"])
    claim_x = _make_claim("claim-x")

    objects_by_id = {"rel-a": rel_a, "rel-b": rel_b, "claim-x": claim_x}
    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.find_object",
        lambda session, oid: objects_by_id.get(oid),
    )

    async def _fake_listing(runtime, arguments):
        return _listing_result(relation_ids=["rel-a", "rel-b"])

    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.resolve_contradiction_tool", _fake_listing
    )

    async def _fake_query_subgraph(runtime, arguments):
        return {"error": "boom"}

    monkeypatch.setattr(
        "cks_mcp.pipeline.arbiter_step.query_subgraph_tool", _fake_query_subgraph
    )

    task = {
        "session_id": "s1",
        "payload": {"location": "rel-a", "code": "CKS-EXT-MUTUAL-EXCLUSION"},
    }
    resolution = await resolve_pipeline_arbitration_request(
        mock_runtime, task, ArbiterStepSettings(storage_path=":memory:")
    )

    assert resolution.resolved is False
    assert "query_subgraph failed" in resolution.detail
