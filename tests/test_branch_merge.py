"""Integration tests for create_branch, merge_branch, and close_session."""

import cks
import pytest
from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.tools.branch import close_session, create_branch
from cks_mcp.tools.evolve import evolve_knowledge
from cks_mcp.tools.merge import merge_branch

pytestmark = pytest.mark.asyncio


def make_runtime() -> Runtime:
    return Runtime(core=CksCoreAdapter())


def make_structure(ids: list[str]) -> str:
    objects = []
    for i in ids:
        obj = cks.KnowledgeObject(cks.ObjectIdentity(id=i, type="Thing", name=i))
        objects.append(obj)
    struct = cks.KnowledgeStructure(objects)
    return cks.serialize(struct)


async def test_create_branch_returns_new_session_id():
    runtime = make_runtime()
    session = await runtime.create_session({})
    result = await create_branch(runtime, {"session_id": session.session_id})
    assert "session_id" in result
    assert result["session_id"] != session.session_id


async def test_create_branch_missing_session_id():
    runtime = make_runtime()
    result = await create_branch(runtime, {})
    assert result["error"] == "missing_parameter"


async def test_close_session_closes_existing_session():
    runtime = make_runtime()
    session = await runtime.create_session({})
    result = await close_session(runtime, {"session_id": session.session_id})
    assert result["closed"] is True
    assert runtime.get_session(session.session_id) is None


async def test_merge_branch_combines_non_conflicting_changes():
    runtime = make_runtime()
    trunk = await runtime.create_session(cks.parse(make_structure(["root"])))
    tx = runtime.begin_transaction(trunk)
    await runtime.commit_transaction(tx)
    branch = await runtime.create_branch(trunk, version_id=trunk.version_history[0].version_id)

    await evolve_knowledge(runtime, {
        "json_data": make_structure(["root"]),
        "session_id": trunk.session_id,
        "operations": [{"type": "add_object", "identity": {"id": "a", "type": "Thing", "name": "a"}}],
    })
    await evolve_knowledge(runtime, {
        "json_data": make_structure(["root"]),
        "session_id": branch.session_id,
        "operations": [{"type": "add_object", "identity": {"id": "b", "type": "Thing", "name": "b"}}],
    })

    result = await merge_branch(runtime, {
        "target_session_id": trunk.session_id,
        "source_session_id": branch.session_id,
    })
    assert result["merged"] is True
    assert "a" in result["serialized"]
    assert "b" in result["serialized"]


async def test_merge_branch_missing_parameters():
    runtime = make_runtime()
    assert (await merge_branch(runtime, {}))["error"] == "missing_parameter"
    assert (await merge_branch(runtime, {"target_session_id": "x"}))["error"] == "missing_parameter"


async def test_merge_branch_unknown_sessions():
    runtime = make_runtime()
    result = await merge_branch(runtime, {"target_session_id": "ghost", "source_session_id": "ghost2"})
    assert result["error"] == "session_not_found"


async def test_merge_branch_detects_conflicts():
    runtime = make_runtime()
    trunk = await runtime.create_session(cks.parse(make_structure(["shared"])))
    tx = runtime.begin_transaction(trunk)
    await runtime.commit_transaction(tx)
    branch = await runtime.create_branch(trunk, version_id=trunk.version_history[0].version_id)

    await evolve_knowledge(runtime, {
        "json_data": make_structure(["shared"]),
        "session_id": trunk.session_id,
        "operations": [
            {"type": "remove_object", "object_id": "shared"},
            {"type": "add_object", "identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "trunk edit"}},
        ],
    })
    await evolve_knowledge(runtime, {
        "json_data": make_structure(["shared"]),
        "session_id": branch.session_id,
        "operations": [
            {"type": "remove_object", "object_id": "shared"},
            {"type": "add_object", "identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "branch edit"}},
        ],
    })

    result = await merge_branch(runtime, {
        "target_session_id": trunk.session_id,
        "source_session_id": branch.session_id,
    })
    assert result["merged"] is False
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["object_id"] == "shared"


async def _make_conflicting_branch(runtime):
    trunk = await runtime.create_session(cks.parse(make_structure(["shared"])))
    tx = runtime.begin_transaction(trunk)
    await runtime.commit_transaction(tx)
    branch = await runtime.create_branch(trunk, version_id=trunk.version_history[0].version_id)

    await evolve_knowledge(runtime, {
        "json_data": make_structure(["shared"]),
        "session_id": trunk.session_id,
        "operations": [
            {"type": "update_object", "object_id": "shared", "structure_patch": {"note": "trunk edit"}},
        ],
    })
    await evolve_knowledge(runtime, {
        "json_data": make_structure(["shared"]),
        "session_id": branch.session_id,
        "operations": [
            {"type": "update_object", "object_id": "shared", "structure_patch": {"note": "branch edit"}},
        ],
    })
    return trunk, branch


async def test_merge_branch_resolutions_branch_a():
    runtime = make_runtime()
    trunk, branch = await _make_conflicting_branch(runtime)
    result = await merge_branch(runtime, {
        "target_session_id": trunk.session_id,
        "source_session_id": branch.session_id,
        "resolutions": {"shared": "branch_a"},
    })
    assert result["merged"] is True
    assert "trunk edit" in result["serialized"]


async def test_merge_branch_resolutions_branch_b():
    runtime = make_runtime()
    trunk, branch = await _make_conflicting_branch(runtime)
    result = await merge_branch(runtime, {
        "target_session_id": trunk.session_id,
        "source_session_id": branch.session_id,
        "resolutions": {"shared": "branch_b"},
    })
    assert result["merged"] is True
    assert "branch edit" in result["serialized"]


async def test_merge_branch_resolutions_custom_object():
    runtime = make_runtime()
    trunk, branch = await _make_conflicting_branch(runtime)
    result = await merge_branch(runtime, {
        "target_session_id": trunk.session_id,
        "source_session_id": branch.session_id,
        "resolutions": {
            "shared": {
                "identity": {"id": "shared", "type": "Thing", "name": "shared"},
                "structure": {"note": "synthesized from both edits"},
            }
        },
    })
    assert result["merged"] is True
    assert "synthesized from both edits" in result["serialized"]


async def test_merge_branch_resolutions_malformed_custom_object():
    runtime = make_runtime()
    trunk, branch = await _make_conflicting_branch(runtime)
    result = await merge_branch(runtime, {
        "target_session_id": trunk.session_id,
        "source_session_id": branch.session_id,
        "resolutions": {"shared": {"structure": {"note": "no identity field"}}},
    })
    assert "error" in result
    assert "resolutions" in result["error"].lower()


async def test_merge_branch_resolutions_partial_leaves_remaining_conflicts():
    runtime = make_runtime()
    trunk = await runtime.create_session(cks.parse(make_structure(["a", "b"])))
    tx = runtime.begin_transaction(trunk)
    await runtime.commit_transaction(tx)
    branch = await runtime.create_branch(trunk, version_id=trunk.version_history[0].version_id)

    await evolve_knowledge(runtime, {
        "json_data": make_structure(["a", "b"]), "session_id": trunk.session_id,
        "operations": [
            {"type": "update_object", "object_id": "a", "structure_patch": {"note": "trunk-a"}},
            {"type": "update_object", "object_id": "b", "structure_patch": {"note": "trunk-b"}},
        ],
    })
    await evolve_knowledge(runtime, {
        "json_data": make_structure(["a", "b"]), "session_id": branch.session_id,
        "operations": [
            {"type": "update_object", "object_id": "a", "structure_patch": {"note": "branch-a"}},
            {"type": "update_object", "object_id": "b", "structure_patch": {"note": "branch-b"}},
        ],
    })

    result = await merge_branch(runtime, {
        "target_session_id": trunk.session_id,
        "source_session_id": branch.session_id,
        "resolutions": {"a": "branch_a"},
    })
    assert result["merged"] is False
    assert [c["object_id"] for c in result["conflicts"]] == ["b"]


async def test_close_session_after_merge():
    runtime = make_runtime()
    trunk = await runtime.create_session(cks.parse(make_structure(["root"])))
    tx = runtime.begin_transaction(trunk)
    await runtime.commit_transaction(tx)
    branch = await runtime.create_branch(trunk, version_id=trunk.version_history[0].version_id)

    await evolve_knowledge(runtime, {
        "json_data": make_structure(["root"]),
        "session_id": trunk.session_id,
        "operations": [{"type": "add_object", "identity": {"id": "a", "type": "Thing", "name": "a"}}],
    })
    await evolve_knowledge(runtime, {
        "json_data": make_structure(["root"]),
        "session_id": branch.session_id,
        "operations": [{"type": "add_object", "identity": {"id": "b", "type": "Thing", "name": "b"}}],
    })

    await merge_branch(runtime, {
        "target_session_id": trunk.session_id,
        "source_session_id": branch.session_id,
    })
    close_result = await close_session(runtime, {"session_id": branch.session_id})
    assert close_result["closed"] is True
    assert runtime.get_session(branch.session_id) is None


async def test_create_branch_from_specific_version():
    runtime = make_runtime()
    trunk = await runtime.create_session(cks.parse(make_structure(["root"])))
    tx = runtime.begin_transaction(trunk)
    await runtime.commit_transaction(tx)
    initial_version_id = trunk.version_history[0].version_id

    await evolve_knowledge(runtime, {
        "json_data": make_structure(["root"]),
        "session_id": trunk.session_id,
        "operations": [{"type": "add_object", "identity": {"id": "a", "type": "Thing", "name": "a"}}],
    })

    branch = await create_branch(runtime, {"session_id": trunk.session_id, "version_id": initial_version_id})
    assert "session_id" in branch
    assert branch["parent_version_id"] == initial_version_id
    branch_session = runtime.get_session(branch["session_id"])
    assert branch_session is not None


async def test_create_branch_invalid_version():
    runtime = make_runtime()
    trunk = await runtime.create_session(cks.parse(make_structure(["root"])))
    result = await create_branch(runtime, {"session_id": trunk.session_id, "version_id": "nonexistent"})
    assert "error" in result


async def test_close_session_twice():
    runtime = make_runtime()
    session = await runtime.create_session({})
    await close_session(runtime, {"session_id": session.session_id})
    result = await close_session(runtime, {"session_id": session.session_id})
    assert result["error"] == "session_not_found"