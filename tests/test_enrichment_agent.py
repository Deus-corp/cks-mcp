"""Unit tests for cks_mcp.enrichment_agent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.agent_loop import Resolution
from cks_mcp.enrichment.adapters import EnrichmentCandidate
from cks_mcp.enrichment_agent import (
    EnrichmentAgentSettings,
    _already_enriched_urls,
    _ops_from_structure,
    resolve_enrichment_request,
    run_once,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Lightweight fakes for session.knowledge_structure -- just enough surface
# (.objects, .relations(), .identity.{id,name}, .structure,
# .relation_type/.participants) for _already_enriched_urls and
# resolve_enrichment_request to walk, without pulling in real cks-core
# objects.
# ---------------------------------------------------------------------------


class _FakeIdentity:
    def __init__(self, id: str, name: str = ""):
        self.id = id
        self.name = name


class _FakeObject:
    def __init__(self, id: str, name: str = "", structure: dict | None = None):
        self.identity = _FakeIdentity(id, name)
        self.structure = structure or {}


class _FakeRelation:
    def __init__(self, relation_type: str, participants: list[str]):
        self.relation_type = relation_type
        self.participants = participants


class _FakeKnowledgeStructure:
    def __init__(self, objects: list[_FakeObject], relations: list[_FakeRelation]):
        self.objects = objects
        self._relations = relations

    def relations(self):
        return self._relations


class _FakeSession:
    def __init__(self, objects: list[_FakeObject], relations: list[_FakeRelation]):
        self.knowledge_structure = _FakeKnowledgeStructure(objects, relations)


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


# ---------------------------------------------------------------------------
# _already_enriched_urls
# ---------------------------------------------------------------------------


def test_already_enriched_urls_finds_linked_document_url():
    obj = _FakeObject("obj-1", "Widget")
    doc = _FakeObject("doc-1", "Widget - Wikipedia", {"url": "https://en.wikipedia.org/wiki/Widget"})
    rel = _FakeRelation("enriched_by", ["obj-1", "doc-1"])
    session = _FakeSession([obj, doc], [rel])

    assert _already_enriched_urls(session, "obj-1") == {"https://en.wikipedia.org/wiki/Widget"}


def test_already_enriched_urls_ignores_other_relation_types_and_objects():
    obj = _FakeObject("obj-1", "Widget")
    doc = _FakeObject("doc-1", "Widget - Wikipedia", {"url": "https://en.wikipedia.org/wiki/Widget"})
    mentions_rel = _FakeRelation("mentions", ["obj-1", "doc-1"])  # wrong relation_type
    other_objects_rel = _FakeRelation("enriched_by", ["obj-2", "doc-1"])  # different object
    session = _FakeSession([obj, doc], [mentions_rel, other_objects_rel])

    assert _already_enriched_urls(session, "obj-1") == set()


def test_already_enriched_urls_empty_when_no_relations():
    obj = _FakeObject("obj-1", "Widget")
    session = _FakeSession([obj], [])

    assert _already_enriched_urls(session, "obj-1") == set()


# ---------------------------------------------------------------------------
# resolve_enrichment_request: dedup against prior enriched_by relations
# ---------------------------------------------------------------------------


async def test_resolve_enrichment_request_skips_already_enriched_candidate(
    mock_runtime, monkeypatch
):
    already_enriched_url = "https://en.wikipedia.org/wiki/Widget"

    obj = _FakeObject("obj-1", "Widget")
    doc = _FakeObject("doc-1", "Widget - Wikipedia", {"url": already_enriched_url})
    rel = _FakeRelation("enriched_by", ["obj-1", "doc-1"])
    session = _FakeSession([obj, doc], [rel])
    mock_runtime.get_session = MagicMock(return_value=session)

    candidate = EnrichmentCandidate(
        url=already_enriched_url, title="Widget", source_adapter="wikipedia", source_kind="wikipedia_article"
    )
    monkeypatch.setattr(
        "cks_mcp.enrichment_agent.build_enrichment_candidates",
        lambda *a, **k: ([candidate], {}),
    )

    # If the dedup check didn't work, resolution would try to reach the
    # network via ingest_document -- fail the test loudly instead of
    # letting that happen silently.
    async def _unexpected_ingest(*_a, **_k):
        raise AssertionError("ingest_document should not be called for an already-enriched URL")

    monkeypatch.setattr("cks_mcp.enrichment_agent.ingest_document", _unexpected_ingest)

    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_enrichment_request(mock_runtime, task, _settings())

    assert resolution.resolved is True
    assert "already enriched" in resolution.detail
    assert already_enriched_url in resolution.detail


async def test_resolve_enrichment_request_still_processes_new_url_when_another_already_enriched(
    mock_runtime, monkeypatch
):
    already_enriched_url = "https://en.wikipedia.org/wiki/Widget"
    new_url = "https://en.wikipedia.org/wiki/Widget_(mechanical_part)"

    obj = _FakeObject("obj-1", "Widget")
    doc = _FakeObject("doc-1", "Widget - Wikipedia", {"url": already_enriched_url})
    rel = _FakeRelation("enriched_by", ["obj-1", "doc-1"])
    session = _FakeSession([obj, doc], [rel])
    mock_runtime.get_session = MagicMock(return_value=session)

    old_candidate = EnrichmentCandidate(
        url=already_enriched_url, title="Widget", source_adapter="wikipedia", source_kind="wikipedia_article"
    )
    new_candidate = EnrichmentCandidate(
        url=new_url, title="Widget (mechanical part)", source_adapter="wikipedia", source_kind="wikipedia_article"
    )
    monkeypatch.setattr(
        "cks_mcp.enrichment_agent.build_enrichment_candidates",
        lambda *a, **k: ([old_candidate, new_candidate], {}),
    )
    monkeypatch.setattr("cks_mcp.enrichment_agent.robots_allows", lambda *_a, **_k: True)

    seen_urls = []

    async def _fake_ingest(_runtime, args):
        seen_urls.append(args["url"])
        return {
            "knowledge_structure": {
                "objects": [
                    {
                        "identity": {"id": "doc-new", "type": "Document", "name": "Widget (mechanical part)"},
                        "structure": {"url": args["url"]},
                    }
                ]
            }
        }

    async def _fake_verify(_runtime, _args):
        return {"objects": []}

    async def _fake_evolve(_runtime, _args):
        return {"ok": True}

    monkeypatch.setattr("cks_mcp.enrichment_agent.ingest_document", _fake_ingest)
    monkeypatch.setattr("cks_mcp.enrichment_agent.verify_source", _fake_verify)
    monkeypatch.setattr("cks_mcp.enrichment_agent.evolve_knowledge", _fake_evolve)

    task = {"session_id": "s1", "payload": {"object_id": "obj-1"}}
    resolution = await resolve_enrichment_request(mock_runtime, task, _settings())

    assert resolution.resolved is True
    assert seen_urls == [new_url]
    assert new_url in resolution.detail
    assert already_enriched_url not in seen_urls