"""Unit tests for cks_mcp.enrichment_agent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.agent_loop import Resolution
from cks_mcp.enrichment_agent import (
    EnrichmentAgentSettings,
    _ops_from_structure,
    resolve_enrichment_request,
    run_once,
)

pytestmark = pytest.mark.asyncio


def _settings(**overrides) -> EnrichmentAgentSettings:
    base = EnrichmentAgentSettings(
        poll_interval=0.01,
        max_retries=3,
        storage_path=":memory:",
        heartbeat_interval=60.0,
        min_score=0.5,
        max_ingests=2,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.dequeue_next_outbox_task = AsyncMock(return_value=None)
    runtime.storage.complete_outbox_task = AsyncMock()
    runtime.storage.fail_outbox_task = AsyncMock()
    runtime.storage.dead_letter_outbox_task = AsyncMock()
    runtime.storage.touch_outbox_task = AsyncMock(return_value=True)
    return runtime


def test_ops_from_structure_converts_objects_and_relations():
    structure = {
        "objects": [
            {
                "identity": {"id": "doc-1", "type": "Document", "name": "Test"},
                "structure": {"url": "https://example.com"},
            },
            {
                "identity": {"id": "rel-1", "type": "Relation", "name": "mentions"},
                "structure": {"participants": ["doc-1", "topic-1"], "relation_type": "mentions"},
            },
        ]
    }
    ops = _ops_from_structure(structure)
    assert len(ops) == 2
    assert ops[0] == {"type": "add_object", "identity": structure["objects"][0]["identity"], "structure": {"url": "https://example.com"}}
    assert ops[1]["type"] == "add_relation"
    assert ops[1]["participants"] == ["doc-1", "topic-1"]
    assert ops[1]["relation_type"] == "mentions"


async def test_resolve_enrichment_request_missing_object_id(mock_runtime):
    task = {"session_id": "s1", "payload": {}}
    resolution = await resolve_enrichment_request(mock_runtime, task, _settings())
    assert resolution.resolved is False
    assert "missing required 'object_id'" in resolution.detail


async def test_resolve_enrichment_request_session_not_found(mock_runtime):
    mock_runtime.get_session = MagicMock(return_value=None)
    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_enrichment_request(mock_runtime, task, _settings())
    assert resolution.resolved is False


async def test_run_once_processes_one_task(mock_runtime, monkeypatch):
    from cks_runtime.storage.storage import OutboxTask

    tasks = [
        OutboxTask(task_id=1, task_type="enrichment_request", session_id="s1", payload='{"object_id":"obj-1"}', retry_count=0),
        None,
    ]
    mock_runtime.storage.dequeue_next_outbox_task = AsyncMock(side_effect=tasks)

    async def _fake_resolver(runtime, task, settings=None):
        return Resolution(True, "done")

    monkeypatch.setattr("cks_mcp.enrichment_agent.resolve_enrichment_request", _fake_resolver)

    processed = await run_once(mock_runtime, _settings(max_retries=1))
    assert processed == 1