"""Unit tests for the explain_graph MCP tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from cks_mcp.tools.explain_graph.handler import explain_graph

# pyproject.toml sets asyncio_mode = "auto", so async test functions are
# picked up automatically -- no pytestmark needed.


def _obj(obj_id: str, obj_type: str, name: str, structure: dict) -> SimpleNamespace:
    return SimpleNamespace(
        identity=SimpleNamespace(id=obj_id, type=obj_type, name=name),
        structure=structure,
    )


def _relation(rel_id: str, relation_type: str, participants: list[str]) -> SimpleNamespace:
    # A relation is identified purely by carrying both relation_type and
    # participants in its structure -- identity.type is deliberately
    # something other than any recognised entity type here, to check
    # that detection doesn't depend on it.
    return _obj(
        rel_id,
        "Relation",
        rel_id,
        {"relation_type": relation_type, "participants": participants},
    )


@dataclass
class _FakeStructure:
    objects: list = field(default_factory=list)


def _mock_runtime(*, graph_record=None, session=None):
    runtime = MagicMock()
    runtime.storage.get_graph = AsyncMock(return_value=graph_record)
    runtime.get_session = MagicMock(return_value=session)
    return runtime


def _session(objects: list) -> SimpleNamespace:
    return SimpleNamespace(knowledge_structure=_FakeStructure(objects=objects))


# ---------------------------------------------------------------------------
# Parameter / graph / session validation
# ---------------------------------------------------------------------------


async def test_missing_name():
    runtime = _mock_runtime()
    result = await explain_graph(runtime, {})
    assert result.get("error") == "missing_parameter"
    runtime.storage.get_graph.assert_not_called()


async def test_graph_not_found():
    runtime = _mock_runtime(graph_record=None)
    result = await explain_graph(runtime, {"name": "unknown"})
    assert result == {"found": False}


async def test_session_not_available():
    runtime = _mock_runtime(
        graph_record={"name": "cks-ecosystem", "session_id": "s1"}, session=None
    )
    result = await explain_graph(runtime, {"name": "cks-ecosystem"})
    assert result["found"] is True
    assert result["error"] == "session_not_available"
    assert "s1" in result["message"]


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------


async def test_full_report_contains_all_expected_sections():
    core = _obj(
        "comp-core", "Component", "cks-core",
        {"version": "1.21.0", "description": "Reference implementation"},
    )
    runtime_comp = _obj(
        "comp-runtime", "Component", "cks-runtime",
        {"version": "1.41.0", "description": "Operational execution platform"},
    )

    mod1 = _obj("mod-1", "Module", "constraints", {})
    mod2 = _obj("mod-2", "Module", "adapters", {})
    orphan_mod = _obj("mod-3", "Module", "orphan_module", {})

    storage_backend = _obj(
        "sb-1", "StorageBackend", "sqlite_storage", {"label": "SQLite"}
    )

    sweeper = _obj("sw-1", "Sweeper", "graph_freshness_sweeper", {})
    critic_agent = _obj(
        "agent-1", "Agent", "critic_agent",
        {"handles": ["gossip", "inference", "provenance"]},
    )
    enrichment_agent = _obj(
        "agent-2", "Agent", "enrichment_agent",
        {"searches": ["Wikipedia", "arXiv"]},
    )

    tool1 = _obj("tool-1", "Tool", "validate_knowledge", {"category": "Knowledge Lifecycle"})
    tool2 = _obj("tool-2", "Tool", "evolve_knowledge", {"category": "Knowledge Lifecycle"})
    tool3 = _obj("tool-3", "Tool", "list_versions", {"category": "Version Control"})

    adr1 = _obj("adr-1", "ADR", "ADR-001-runtime-layering", {})

    plugin1 = _obj(
        "plugin-1", "Plugin", "FastEmbedPlugin",
        {"status": "available", "description": "Embedding provider"},
    )

    relations = [
        _relation("rel-1", "contains", ["comp-core", "mod-1"]),
        _relation("rel-2", "contains", ["comp-core", "mod-2"]),
        _relation("rel-3", "contains", ["comp-runtime", "adr-1"]),
        _relation("rel-4", "resolves", ["sw-1", "agent-1"]),
        # Dangling relation -- "ghost-id" isn't any object in the graph.
        _relation("rel-5", "contains", ["comp-core", "ghost-id"]),
    ]

    objects = [
        core, runtime_comp,
        mod1, mod2, orphan_mod,
        storage_backend,
        sweeper, critic_agent, enrichment_agent,
        tool1, tool2, tool3,
        adr1,
        plugin1,
        *relations,
    ]

    runtime = _mock_runtime(
        graph_record={
            "name": "cks-ecosystem",
            "session_id": "s1",
            "description": "The CKS ecosystem, describing itself",
            "updated_at": "2026-08-01T00:00:00Z",
        },
        session=_session(objects),
    )

    result = await explain_graph(runtime, {"name": "cks-ecosystem"})

    assert result["found"] is True
    assert result["name"] == "cks-ecosystem"
    assert result["session_id"] == "s1"
    report = result["report"]

    # Header
    assert "# Graph: cks-ecosystem" in report
    assert "**Description:** The CKS ecosystem, describing itself" in report
    assert "**Session ID:** s1" in report

    # Components
    assert "## Components" in report
    assert "`cks-core` (v1.21.0) — Reference implementation" in report
    assert "`cks-runtime` (v1.41.0) — Operational execution platform" in report

    # Modules, grouped under their component + an orphan bucket
    assert "## Modules" in report
    assert "### cks-core (2 modules)" in report
    assert "`constraints`" in report and "`adapters`" in report
    assert "### Other Modules (1 modules)" in report
    assert "`orphan_module`" in report

    # Storage backends
    assert "## Storage Backends" in report
    assert "`sqlite_storage` (SQLite)" in report

    # Sweepers with resolved relation names
    assert "## Sweepers (1)" in report
    assert "`graph_freshness_sweeper` — resolves: critic_agent" in report

    # Agents, reading structure fields directly
    assert "## Agents (2)" in report
    assert "`critic_agent` — handles: gossip, inference, provenance" in report
    assert "`enrichment_agent` — searches: Wikipedia, arXiv" in report

    # Tools grouped by category
    assert "## Tools (3)" in report
    assert "**Knowledge Lifecycle:** evolve_knowledge, validate_knowledge" in report
    assert "**Version Control:** list_versions" in report

    # ADRs grouped under their component
    assert "## ADRs" in report
    assert "### cks-runtime (1 ADRs)" in report
    assert "`ADR-001-runtime-layering`" in report

    # Plugins
    assert "## Plugins" in report
    assert "`FastEmbedPlugin` (available) — Embedding provider" in report

    # Anomalies: the dangling relation is flagged
    assert "## Anomalies" in report
    assert "Dangling relation `rel-5`: references missing object `ghost-id`" in report

    # Summary counts
    assert "## Summary" in report
    assert "**Components:** 2" in report
    assert "**Modules:** 3" in report
    assert "**Storage Backends:** 1" in report
    assert "**Sweepers:** 1" in report
    assert "**Agents:** 2" in report
    assert "**Tools:** 3" in report
    assert "**ADRs:** 1" in report
    assert "**Plugins:** 1" in report
    assert f"**Total Objects:** {len(objects) - len(relations)}" in report
    assert f"**Total Relations:** {len(relations)}" in report
    assert "**Contradictions:** 0" in report


# ---------------------------------------------------------------------------
# Empty graph
# ---------------------------------------------------------------------------


async def test_empty_graph_gives_minimal_report_without_entity_sections():
    runtime = _mock_runtime(
        graph_record={"name": "empty-graph", "session_id": "s2"},
        session=_session([]),
    )

    result = await explain_graph(runtime, {"name": "empty-graph"})

    assert result["found"] is True
    report = result["report"]

    # Header, Anomalies and Summary are always present...
    assert "# Graph: empty-graph" in report
    assert "## Anomalies" in report
    assert "None detected" in report
    assert "## Summary" in report
    assert "**Total Objects:** 0" in report
    assert "**Total Relations:** 0" in report

    # ...but every entity-type section is omitted entirely.
    for heading in (
        "## Components",
        "## Modules",
        "## Storage Backends",
        "## Sweepers",
        "## Agents",
        "## Tools",
        "## ADRs",
        "## Plugins",
        "## Interfaces",
        "## Tasks",
    ):
        assert heading not in report


async def test_graph_with_only_unrecognised_objects_has_no_entity_sections():
    plain = _obj("o1", "SomethingElse", "n1", {})
    runtime = _mock_runtime(
        graph_record={"name": "g1", "session_id": "s3"},
        session=_session([plain]),
    )

    result = await explain_graph(runtime, {"name": "g1"})

    report = result["report"]
    assert "**Total Objects:** 1" in report
    assert "## Components" not in report
    assert "## Anomalies" in report
    assert "None detected" in report
