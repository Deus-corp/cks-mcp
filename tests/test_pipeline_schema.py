"""Unit tests for cks_mcp.pipeline.schema."""

from __future__ import annotations

from cks_mcp.pipeline.schema import (
    PipelineStatus,
    append_transition,
    has_agent_transitioned,
    read_status,
    read_transition_log,
)


def test_read_status_from_dict():
    obj = {"structure": {"current_status": PipelineStatus.AWAITING_REVIEW}}
    assert read_status(obj) == PipelineStatus.AWAITING_REVIEW


def test_read_status_missing_structure():
    assert read_status({"structure": {}}) is None


def test_read_transition_log_empty_default():
    assert read_transition_log({"structure": {}}) == []


def test_append_transition_builds_update_object_op():
    op = append_transition(
        "obj-1",
        agent="ResearcherAgent",
        action="researched",
        transitioned_to=PipelineStatus.AWAITING_REVIEW,
        current_log=[],
        reasoning_node_id="finding-1",
        content_hash="abc123",
    )
    assert op["type"] == "update_object"
    assert op["object_id"] == "obj-1"
    assert op["mode"] == "merge"
    patch = op["structure_patch"]
    assert patch["current_status"] == PipelineStatus.AWAITING_REVIEW
    assert len(patch["transition_log"]) == 1
    entry = patch["transition_log"][0]
    assert entry["agent"] == "ResearcherAgent"
    assert entry["transitioned_to"] == PipelineStatus.AWAITING_REVIEW
    assert entry["reasoning_node_id"] == "finding-1"
    assert entry["content_hash"] == "abc123"


def test_append_transition_preserves_prior_entries():
    prior = [{"agent": "ResearcherAgent", "transitioned_to": "awaiting_review"}]
    op = append_transition(
        "obj-1",
        agent="ReviewerAgent",
        action="reviewed",
        transitioned_to=PipelineStatus.RESOLVED,
        current_log=prior,
    )
    log = op["structure_patch"]["transition_log"]
    assert len(log) == 2
    assert log[0]["agent"] == "ResearcherAgent"
    assert log[1]["agent"] == "ReviewerAgent"


def test_has_agent_transitioned_false_when_absent():
    obj = {"structure": {"transition_log": []}}
    assert has_agent_transitioned(obj, "ReviewerAgent") is False


def test_has_agent_transitioned_true_when_present():
    obj = {"structure": {"transition_log": [{"agent": "ReviewerAgent", "content_hash": "h1"}]}}
    assert has_agent_transitioned(obj, "ReviewerAgent") is True


def test_has_agent_transitioned_respects_content_hash():
    obj = {"structure": {"transition_log": [{"agent": "ReviewerAgent", "content_hash": "h1"}]}}
    assert has_agent_transitioned(obj, "ReviewerAgent", content_hash="h2") is False
    assert has_agent_transitioned(obj, "ReviewerAgent", content_hash="h1") is True