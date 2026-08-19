"""Integration tests for the compare_graphs MCP tool."""

from __future__ import annotations

import json

import cks
import pytest
from cks_runtime.adapters.cks_core import CksCoreAdapter
from cks_runtime.runtime import Runtime

from cks_mcp.tools.compare_graphs.handler import compare_graphs
from cks_mcp.tools.register_graph.handler import register_graph

pytestmark = pytest.mark.asyncio


def make_runtime() -> Runtime:
    return Runtime(core=CksCoreAdapter())


def make_object(object_id: str, version: str = "1.0.0") -> cks.KnowledgeObject:
    return cks.KnowledgeObject(
        cks.ObjectIdentity(id=object_id, type="Thing", name=object_id),
        structure={"version": version},
    )


def make_relation(relation_id: str, a: str, b: str) -> cks.KnowledgeObject:
    payload = {
        "objects": [
            {
                "identity": {"id": relation_id, "type": "Relation", "name": relation_id},
                "structure": {"participants": [a, b], "relation_type": "relates_to"},
            }
        ]
    }
    return cks.parse(json.dumps(payload)).objects[0]


async def make_session(runtime: Runtime, objects: list) -> object:
    structure = cks.KnowledgeStructure(objects)
    session = await runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    await runtime.commit_transaction(tx)
    return session


async def test_compare_by_session_id():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("a"), make_object("shared")])
    session_b = await make_session(runtime, [make_object("b"), make_object("shared")])

    result = await compare_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
        },
    )

    assert result["shared_object_count"] == 1
    assert result["shared_object_ids"] == ["shared"]
    assert result["only_in_a"] == ["a"]
    assert result["only_in_b"] == ["b"]
    assert result["only_in_a_count"] == 1
    assert result["only_in_b_count"] == 1


async def test_compare_by_graph_name():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("a")])
    session_b = await make_session(runtime, [make_object("b")])
    await register_graph(runtime, {"name": "proj-a", "session_id": session_a.session_id})
    await register_graph(runtime, {"name": "proj-b", "session_id": session_b.session_id})

    result = await compare_graphs(
        runtime, {"graph_a_name": "proj-a", "graph_b_name": "proj-b"}
    )

    assert result["graph_a"] == "proj-a"
    assert result["graph_b"] == "proj-b"
    assert result["graph_a_session_id"] == session_a.session_id
    assert result["graph_b_session_id"] == session_b.session_id


async def test_detects_structural_differences_for_shared_objects():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("shared", version="1.0.0")])
    session_b = await make_session(runtime, [make_object("shared", version="1.1.0")])

    result = await compare_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
        },
    )

    assert result["shared_object_ids"] == ["shared"]
    assert len(result["differences"]) == 1
    diff = result["differences"][0]
    assert diff["id"] == "shared"
    assert diff["action"] == "modified"
    assert diff["changes"]["version"] == {"from": "1.0.0", "to": "1.1.0"}


async def test_include_relations_false_excludes_relation_ids():
    runtime = make_runtime()
    session_a = await make_session(
        runtime, [make_object("a"), make_object("b"), make_relation("rel-1", "a", "b")]
    )
    session_b = await make_session(
        runtime, [make_object("a"), make_object("b"), make_relation("rel-1", "a", "b")]
    )

    with_relations = await compare_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
        },
    )
    without_relations = await compare_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
            "include_relations": False,
        },
    )

    assert "rel-1" in with_relations["shared_object_ids"]
    assert "rel-1" not in without_relations["shared_object_ids"]
    assert without_relations["shared_object_count"] == 2


async def test_never_mutates_either_source():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("a")])
    session_b = await make_session(runtime, [make_object("b")])
    hash_a_before = session_a.knowledge_structure.root_hash
    hash_b_before = session_b.knowledge_structure.root_hash

    await compare_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
        },
    )

    assert session_a.knowledge_structure.root_hash == hash_a_before
    assert session_b.knowledge_structure.root_hash == hash_b_before


async def test_missing_both_sides_returns_error():
    runtime = make_runtime()
    result = await compare_graphs(runtime, {})
    assert result["error"] == "missing_parameter"


async def test_unknown_graph_name_returns_graph_not_found():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("a")])
    result = await compare_graphs(
        runtime,
        {"graph_a_session_id": session_a.session_id, "graph_b_name": "nope"},
    )
    assert result["error"] == "graph_not_found"