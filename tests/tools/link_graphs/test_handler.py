"""Integration tests for the link_graphs MCP tool."""

from __future__ import annotations

import cks
import pytest
from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.tools.link_graphs.handler import link_graphs
from cks_mcp.tools.register_graph.handler import register_graph

pytestmark = pytest.mark.asyncio


def make_runtime() -> Runtime:
    return Runtime(core=CksCoreAdapter())


def make_object(object_id: str) -> cks.KnowledgeObject:
    return cks.KnowledgeObject(cks.ObjectIdentity(id=object_id, type="Thing", name=object_id))


async def make_session(runtime: Runtime, objects: list) -> object:
    structure = cks.KnowledgeStructure(objects)
    session = await runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    await runtime.commit_transaction(tx)
    return session


async def test_link_by_session_id_writes_relation_to_both_graphs():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("obj-a")])
    session_b = await make_session(runtime, [make_object("obj-b")])

    result = await link_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
            "object_a_id": "obj-a",
            "object_b_id": "obj-b",
            "relation_type": "depends_on",
        },
    )

    assert result["linked"] is True
    assert result["graph_a_version"]
    assert result["graph_b_version"]

    relation_id = result["relation_id"]
    assert relation_id in session_a.knowledge_structure
    assert relation_id in session_b.knowledge_structure

    rel_in_a = session_a.knowledge_structure.get(relation_id)
    rel_in_b = session_b.knowledge_structure.get(relation_id)
    assert rel_in_a.structure["participants"] == ("obj-a", "obj-b")
    assert rel_in_b.structure["participants"] == ("obj-a", "obj-b")
    assert rel_in_a.structure["relation_type"] == "depends_on"

    # Existing objects untouched.
    assert "obj-a" in session_a.knowledge_structure
    assert "obj-b" in session_b.knowledge_structure


async def test_link_by_graph_name():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("obj-a")])
    session_b = await make_session(runtime, [make_object("obj-b")])
    await register_graph(runtime, {"name": "proj-a", "session_id": session_a.session_id})
    await register_graph(runtime, {"name": "proj-b", "session_id": session_b.session_id})

    result = await link_graphs(
        runtime,
        {
            "graph_a_name": "proj-a",
            "graph_b_name": "proj-b",
            "object_a_id": "obj-a",
            "object_b_id": "obj-b",
            "relation_type": "references",
        },
    )

    assert result["linked"] is True
    assert "proj-a" in result["relation_id"]
    assert "proj-b" in result["relation_id"]


async def test_missing_object_a_returns_error():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("obj-a")])
    session_b = await make_session(runtime, [make_object("obj-b")])

    result = await link_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
            "object_a_id": "does-not-exist",
            "object_b_id": "obj-b",
            "relation_type": "depends_on",
        },
    )

    assert result["error"] == "object_not_found"
    assert "does-not-exist" in result["message"]


async def test_missing_object_b_returns_error():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("obj-a")])
    session_b = await make_session(runtime, [make_object("obj-b")])

    result = await link_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
            "object_a_id": "obj-a",
            "object_b_id": "does-not-exist",
            "relation_type": "depends_on",
        },
    )

    assert result["error"] == "object_not_found"


async def test_duplicate_link_is_rejected():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("obj-a")])
    session_b = await make_session(runtime, [make_object("obj-b")])
    args = {
        "graph_a_session_id": session_a.session_id,
        "graph_b_session_id": session_b.session_id,
        "object_a_id": "obj-a",
        "object_b_id": "obj-b",
        "relation_type": "depends_on",
    }

    first = await link_graphs(runtime, args)
    assert first["linked"] is True

    second = await link_graphs(runtime, args)
    assert second["error"] == "relation_already_exists"


async def test_missing_required_fields_return_error():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("obj-a")])
    session_b = await make_session(runtime, [make_object("obj-b")])

    result = await link_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_session_id": session_b.session_id,
            "object_a_id": "obj-a",
            # object_b_id and relation_type missing
        },
    )
    assert result["error"] == "missing_parameter"


async def test_unknown_graph_side_returns_error():
    runtime = make_runtime()
    session_a = await make_session(runtime, [make_object("obj-a")])

    result = await link_graphs(
        runtime,
        {
            "graph_a_session_id": session_a.session_id,
            "graph_b_name": "does-not-exist",
            "object_a_id": "obj-a",
            "object_b_id": "obj-b",
            "relation_type": "depends_on",
        },
    )
    assert result["error"] == "graph_not_found"