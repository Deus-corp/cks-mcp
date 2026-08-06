"""Unit tests for the review_dead_letter MCP tool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from cks_runtime.storage.storage import OutboxTask

from cks_mcp.tools.review_dead_letter.handler import review_dead_letter

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.list_dead_letter_tasks = AsyncMock(return_value=[])
    return runtime


async def test_unsupported_backend_reports_error(mock_runtime):
    mock_runtime.storage.supports_outbox = False

    result = await review_dead_letter(mock_runtime, {"task_id": 1})

    assert result["error"] == "not_supported"
    mock_runtime.storage.list_dead_letter_tasks.assert_not_called()


async def test_task_not_found_reports_error(mock_runtime):
    result = await review_dead_letter(mock_runtime, {"task_id": 999})

    assert result["error"] == "task_not_dead_lettered"


async def test_gossip_conflict_proposes_resolve_gossip_conflict(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=1,
                task_type="gossip_conflict",
                session_id="s1",
                payload=json.dumps({"source_session_id": "s2"}),
                retry_count=3,
                last_error="merge_branch reported 2 structural conflict(s)",
            )
        ]
    )

    result = await review_dead_letter(mock_runtime, {"task_id": 1})

    assert result["task_id"] == 1
    assert result["task_type"] == "gossip_conflict"
    assert result["session_id"] == "s1"
    assert result["retry_count"] == 3
    assert result["last_error"] == "merge_branch reported 2 structural conflict(s)"
    assert result["proposed_resolution"] == {
        "tool": "resolve_gossip_conflict",
        "arguments": {"target_session_id": "s1", "source_session_id": "s2"},
    }


async def test_gossip_conflict_missing_source_session_id(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=2,
                task_type="gossip_conflict",
                session_id="s1",
                payload=json.dumps({}),
                retry_count=1,
            )
        ]
    )

    result = await review_dead_letter(mock_runtime, {"task_id": 2})

    assert result["proposed_resolution"]["error"] == "cannot_propose"


async def test_inference_conflict_confidence_conflict_proposes_batch_arbitrate(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=3,
                task_type="inference_conflict",
                session_id="s1",
                payload=json.dumps(
                    {
                        "diagnostics": [
                            {
                                "code": "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT",
                                "location": "obj-1",
                            }
                        ]
                    }
                ),
                retry_count=2,
            )
        ]
    )

    result = await review_dead_letter(mock_runtime, {"task_id": 3})

    assert result["proposed_resolution"] == {
        "tool": "arbitrate_inference_conflict",
        "arguments": {
            "session_id": "s1",
            "conclusion_ids": ["obj-1"],
            "auto_resolve": True,
            "commit": True,
        },
    }


async def test_inference_conflict_stale_premise_proposes_mechanical_arbitrate(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=4,
                task_type="inference_conflict",
                session_id="s1",
                payload=json.dumps(
                    {
                        "diagnostics": [
                            {"code": "CKS-EXT-STALE-PREMISE", "location": "step-1"}
                        ]
                    }
                ),
                retry_count=2,
            )
        ]
    )

    result = await review_dead_letter(mock_runtime, {"task_id": 4})

    assert result["proposed_resolution"] == {
        "tool": "arbitrate_inference_conflict",
        "arguments": {
            "session_id": "s1",
            "stale_premise_ids": ["step-1"],
            "commit": True,
        },
    }


async def test_provenance_conflict_proposes_refresh_verification(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=5,
                task_type="provenance_conflict",
                session_id="s1",
                payload=json.dumps(
                    {
                        "record_id": "rec-1",
                        "subject_id": "doc-1",
                        "source_url": "https://example.com",
                    }
                ),
                retry_count=1,
            )
        ]
    )

    result = await review_dead_letter(mock_runtime, {"task_id": 5})

    assert result["proposed_resolution"] == {
        "tool": "refresh_verification",
        "arguments": {
            "session_id": "s1",
            "record_id": "rec-1",
            "subject_id": "doc-1",
            "source_url": "https://example.com",
            "auto_resolve": True,
            "commit": True,
        },
    }


async def test_provenance_conflict_missing_source_url(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=6,
                task_type="provenance_conflict",
                session_id="s1",
                payload=json.dumps({"record_id": "rec-1", "subject_id": "doc-1"}),
                retry_count=1,
            )
        ]
    )

    result = await review_dead_letter(mock_runtime, {"task_id": 6})

    assert result["proposed_resolution"]["error"] == "cannot_propose"


async def test_temporal_conflict_proposes_bump(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=7,
                task_type="temporal_conflict",
                session_id="s1",
                payload=json.dumps({"object_id": "obj-9"}),
                retry_count=0,
            )
        ]
    )

    result = await review_dead_letter(mock_runtime, {"task_id": 7})

    assert result["proposed_resolution"] == {
        "tool": "resolve_temporal_conflict",
        "arguments": {
            "session_id": "s1",
            "object_id": "obj-9",
            "action": "bump",
            "extend_by_days": 30,
            "commit": True,
        },
    }


async def test_contradiction_detected_proposes_resolve_contradiction(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=8,
                task_type="contradiction_detected",
                session_id="s1",
                payload=json.dumps({"location": "rel-1"}),
                retry_count=0,
            )
        ]
    )

    result = await review_dead_letter(mock_runtime, {"task_id": 8})

    assert result["proposed_resolution"] == {
        "tool": "resolve_contradiction",
        "arguments": {
            "session_id": "s1",
            "contradiction_ids": ["rel-1"],
            "commit": True,
        },
    }


async def test_unknown_task_type_reports_error(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=9,
                task_type="some_new_conflict_type",
                session_id="s1",
                payload=json.dumps({}),
                retry_count=0,
            )
        ]
    )

    result = await review_dead_letter(mock_runtime, {"task_id": 9})

    assert result["proposed_resolution"]["error"] == "unknown_task_type"


async def test_unparseable_payload_is_passed_through(mock_runtime):
    mock_runtime.storage.list_dead_letter_tasks = AsyncMock(
        return_value=[
            OutboxTask(
                task_id=10,
                task_type="gossip_conflict",
                session_id="s1",
                payload="not json",
                retry_count=0,
            )
        ]
    )

    result = await review_dead_letter(mock_runtime, {"task_id": 10})

    assert result["payload"] == "not json"
    assert result["proposed_resolution"]["error"] == "cannot_propose"
