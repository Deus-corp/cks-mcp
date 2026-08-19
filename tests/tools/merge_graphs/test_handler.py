"""Integration tests for the merge_graphs MCP tool."""

from __future__ import annotations

import cks
import pytest
from cks_runtime.adapters.cks_core import CksCoreAdapter
from cks_runtime.runtime import Runtime

from cks_mcp.tools.merge_graphs.handler import merge_graphs
from cks_mcp.tools.register_graph.handler import register_graph

pytestmark = pytest.mark.asyncio


def make_runtime() -> Runtime:
    return Runtime(core=CksCoreAdapter())


def make_object(object_id: str, version: str = "1.0.0") -> cks.KnowledgeObject:
    return cks.KnowledgeObject(
        cks.ObjectIdentity(id=object_id, type="Thing", name=object_id),
        structure={"version": version},
    )


async def make_session(runtime: Runtime, objects: list) -> object:
    structure = cks.KnowledgeStructure(objects)
    session = await runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    await runtime.commit_transaction(tx)
    return session


async def test_merge_two_disjoint_graphs_creates_new_session():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("a")])
    session_b = await make_session(runtime, [make_object("b")])

    result = await merge_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
        },
    )

    assert result["merged"] is True
    assert result["session_id"] not in (session_a.session_id, session_b.session_id)
    assert result["object_count"] == 2

    merged_session = runtime.get_session(result["session_id"])
    assert {o.identity.id for o in merged_session.knowledge_structure.objects} == {"a", "b"}


async def test_merge_by_graph_name_with_register_as():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("a")])
    session_b = await make_session(runtime, [make_object("b")])
    await register_graph(runtime, {"name": "proj-a", "session_id": session_a.session_id})
    await register_graph(runtime, {"name": "proj-b", "session_id": session_b.session_id})

    result = await merge_graphs(
        runtime,
        {"graph_a_name": "proj-a", "graph_b_name": "proj-b", "register_as": "merged"},
    )

    assert result["merged"] is True
    assert result["registered_as"] == "merged"


async def test_conflicting_object_without_resolution_reports_conflict():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("shared", version="1.0.0")])
    session_b = await make_session(runtime, [make_object("shared", version="2.0.0")])

    result = await merge_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
        },
    )

    assert result["merged"] is False
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["object_id"] == "shared"


async def test_conflict_resolved_via_resolutions_argument():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("shared", version="1.0.0")])
    session_b = await make_session(runtime, [make_object("shared", version="2.0.0")])

    result = await merge_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
            "resolutions": {"shared": "branch_b"},
        },
    )

    assert result["merged"] is True
    merged_session = runtime.get_session(result["session_id"])
    merged_obj = merged_session.knowledge_structure.get("shared")
    assert merged_obj.structure["version"] == "2.0.0"


async def test_merge_with_explicit_base_avoids_spurious_conflict():
    runtime = make_runtime()
    base_session = await make_session(runtime, [make_object("shared", version="1.0.0")])
    # Both branches evolve from the same base, only branch B actually changes it —
    # this is NOT a conflict per KnowledgeStructure.merge's own contract.
    session_a = await make_session(runtime, [make_object("shared", version="1.0.0")])
    session_b = await make_session(runtime, [make_object("shared", version="2.0.0")])

    result = await merge_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
            "base_session_id": base_session.session_id,
        },
    )

    assert result["merged"] is True
    merged_session = runtime.get_session(result["session_id"])
    assert merged_session.knowledge_structure.get("shared").structure["version"] == "2.0.0"


async def test_never_mutates_either_source():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("a")])
    session_b = await make_session(runtime, [make_object("b")])
    hash_a_before = session_a.knowledge_structure.root_hash
    hash_b_before = session_b.knowledge_structure.root_hash

    await merge_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
        },
    )

    assert session_a.knowledge_structure.root_hash == hash_a_before
    assert session_b.knowledge_structure.root_hash == hash_b_before


async def test_missing_sides_returns_error():
    runtime = make_runtime()
    result = await merge_graphs(runtime, {})
    assert result["error"] == "missing_parameter"