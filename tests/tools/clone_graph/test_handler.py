"""Integration tests for the clone_graph MCP tool."""

from __future__ import annotations

import json

import cks
import pytest
from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.tools.clone_graph.handler import clone_graph
from cks_mcp.tools.register_graph.handler import register_graph

pytestmark = pytest.mark.asyncio


def make_runtime() -> Runtime:
    return Runtime(core=CksCoreAdapter())


def make_object(object_id: str) -> cks.KnowledgeObject:
    return cks.KnowledgeObject(cks.ObjectIdentity(id=object_id, type="Thing", name=object_id))


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


async def make_source_session(runtime: Runtime):
    structure = cks.KnowledgeStructure(
        [make_object("a"), make_object("b"), make_relation("rel-1", "a", "b")]
    )
    session = await runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    await runtime.commit_transaction(tx)
    return session


async def test_clone_by_source_session_id_creates_new_session():
    runtime = make_runtime()
    source = await make_source_session(runtime)

    result = await clone_graph(runtime, {"source_session_id": source.session_id})

    assert result["session_id"] != source.session_id
    assert result["source_session_id"] == source.session_id
    assert result["imported_objects"] == 2
    assert result["imported_relations"] == 1
    assert result["version_id"]

    new_session = runtime.get_session(result["session_id"])
    assert new_session is not None
    assert {o.identity.id for o in new_session.knowledge_structure.objects} == {"a", "b", "rel-1"}


async def test_clone_by_graph_name():
    runtime = make_runtime()
    source = await make_source_session(runtime)
    await register_graph(runtime, {"name": "proj-a", "session_id": source.session_id})

    result = await clone_graph(runtime, {"graph_name": "proj-a"})

    assert result["source_session_id"] == source.session_id
    assert result["source_graph_name"] == "proj-a"
    assert result["session_id"] != source.session_id


async def test_source_session_id_takes_precedence_over_graph_name():
    runtime = make_runtime()
    source = await make_source_session(runtime)
    other = await runtime.create_session(cks.KnowledgeStructure([make_object("z")]))
    await register_graph(runtime, {"name": "proj-a", "session_id": other.session_id})

    result = await clone_graph(
        runtime,
        {"graph_name": "proj-a", "source_session_id": source.session_id},
    )

    assert result["source_session_id"] == source.session_id
    assert "source_graph_name" not in result


async def test_clone_into_existing_target_session_merges_new_objects():
    runtime = make_runtime()
    source = await make_source_session(runtime)

    target_structure = cks.KnowledgeStructure([make_object("a"), make_object("c")])
    target = await runtime.create_session(target_structure)
    tx = runtime.begin_transaction(target)
    await runtime.commit_transaction(tx)

    result = await clone_graph(
        runtime,
        {"source_session_id": source.session_id, "target_session_id": target.session_id},
    )

    assert result["session_id"] == target.session_id
    # "a" already existed in target -- only "b" and "rel-1" are new.
    assert result["imported_objects"] == 1
    assert result["imported_relations"] == 1
    assert result["version_id"]

    ids = {o.identity.id for o in target.knowledge_structure.objects}
    assert ids == {"a", "b", "c", "rel-1"}


async def test_clone_into_target_already_containing_everything_is_a_noop():
    runtime = make_runtime()
    source = await make_source_session(runtime)

    target = await runtime.create_session(
        cks.KnowledgeStructure([make_object("a"), make_object("b"), make_relation("rel-1", "a", "b")])
    )
    tx = runtime.begin_transaction(target)
    await runtime.commit_transaction(tx)

    result = await clone_graph(
        runtime,
        {"source_session_id": source.session_id, "target_session_id": target.session_id},
    )

    assert result["imported_objects"] == 0
    assert result["imported_relations"] == 0
    assert result["version_id"] is None


async def test_missing_source_returns_error():
    runtime = make_runtime()
    result = await clone_graph(runtime, {})
    assert result["error"] == "missing_parameter"


async def test_unknown_graph_name_returns_error():
    runtime = make_runtime()
    result = await clone_graph(runtime, {"graph_name": "ghost"})
    assert result["error"] == "graph_not_found"


async def test_unknown_source_session_id_returns_error():
    runtime = make_runtime()
    result = await clone_graph(runtime, {"source_session_id": "ghost"})
    assert result["error"] == "session_not_found"


async def test_clone_with_copy_name_registers_new_graph():
    runtime = make_runtime()
    source = await make_source_session(runtime)

    result = await clone_graph(
        runtime,
        {"source_session_id": source.session_id, "copy_name": "proj-a-clone", "public": True},
    )

    assert result["registered_as"] == "proj-a-clone"
    record = await runtime.storage.get_graph("proj-a-clone")
    assert record is not None
    assert record["session_id"] == result["session_id"]
    assert record["public"] is True
    # Cloned via source_session_id (not graph_name), so there's no
    # registry name to record as lineage.
    assert record["source_graph_name"] is None


async def test_clone_by_graph_name_records_lineage_on_the_copy():
    runtime = make_runtime()
    source = await make_source_session(runtime)
    await register_graph(runtime, {"name": "proj-a", "session_id": source.session_id})

    result = await clone_graph(
        runtime,
        {"graph_name": "proj-a", "copy_name": "proj-a-fork"},
    )

    assert result["registered_as"] == "proj-a-fork"
    assert result["source_graph_name"] == "proj-a"
    record = await runtime.storage.get_graph("proj-a-fork")
    assert record is not None
    assert record["source_graph_name"] == "proj-a"


async def test_re_registering_a_clone_preserves_its_lineage():
    runtime = make_runtime()
    source = await make_source_session(runtime)
    await register_graph(runtime, {"name": "proj-a", "session_id": source.session_id})
    result = await clone_graph(runtime, {"graph_name": "proj-a", "copy_name": "proj-a-fork"})

    # A plain re-register (e.g. via update_registered_graph editing the
    # description) doesn't pass source_graph_name and must not erase the
    # lineage recorded above.
    await register_graph(
        runtime,
        {"name": "proj-a-fork", "session_id": result["session_id"], "description": "updated"},
    )

    record = await runtime.storage.get_graph("proj-a-fork")
    assert record["description"] == "updated"
    assert record["source_graph_name"] == "proj-a"


async def test_copy_name_ignored_when_target_session_id_given():
    runtime = make_runtime()
    source = await make_source_session(runtime)
    target = await runtime.create_session(cks.KnowledgeStructure([make_object("x")]))
    tx = runtime.begin_transaction(target)
    await runtime.commit_transaction(tx)

    result = await clone_graph(
        runtime,
        {
            "source_session_id": source.session_id,
            "target_session_id": target.session_id,
            "copy_name": "should-not-register",
        },
    )

    assert "registered_as" not in result
    record = await runtime.storage.get_graph("should-not-register")
    assert record is None


async def test_source_session_unchanged_after_clone():
    runtime = make_runtime()
    source = await make_source_session(runtime)
    before_ids = {o.identity.id for o in source.knowledge_structure.objects}
    before_root_hash = source.knowledge_structure.root_hash

    target = await runtime.create_session(cks.KnowledgeStructure([make_object("z")]))
    tx = runtime.begin_transaction(target)
    await runtime.commit_transaction(tx)
    await clone_graph(
        runtime,
        {"source_session_id": source.session_id, "target_session_id": target.session_id},
    )
    await clone_graph(runtime, {"source_session_id": source.session_id})

    after_ids = {o.identity.id for o in source.knowledge_structure.objects}
    assert after_ids == before_ids
    assert source.knowledge_structure.root_hash == before_root_hash
