"""
Integration tests for create_branch, merge_branch, and close_session.
"""

import cks
import pytest
from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.tools.branch import create_branch, close_session
from cks_mcp.tools.merge import merge_branch
from cks_mcp.tools.evolve import evolve_knowledge

def make_runtime() -> Runtime:
    return Runtime(core=CksCoreAdapter())

def make_structure(ids: list[str]) -> str:
    objects = []
    for i in ids:
        obj = cks.KnowledgeObject(cks.ObjectIdentity(id=i, type="Thing", name=i))
        objects.append(obj)
    struct = cks.KnowledgeStructure(objects)
    return cks.serialize(struct)

def test_create_branch_returns_new_session_id():
    runtime = make_runtime()
    result = create_branch(runtime, {"session_id": runtime.create_session({}).session_id})
    assert "session_id" in result
    assert result["session_id"] != runtime.create_session({}).session_id

def test_create_branch_missing_session_id():
    runtime = make_runtime()
    result = create_branch(runtime, {})
    assert result["error"] == "missing_parameter"

def test_close_session_closes_existing_session():
    runtime = make_runtime()
    session = runtime.create_session({})
    result = close_session(runtime, {"session_id": session.session_id})
    assert result["closed"] is True
    assert runtime.get_session(session.session_id) is None

def test_merge_branch_combines_non_conflicting_changes():
    runtime = make_runtime()
    trunk = runtime.create_session(cks.parse(make_structure(["root"])))
    # Commit initial version so branch can record parent_version_id
    tx = runtime.begin_transaction(trunk)
    runtime.commit_transaction(tx)
    branch = runtime.create_branch(trunk, version_id=trunk.version_history[0].version_id)

    # evolve trunk and branch independently
    evolve_knowledge(runtime, {
        "json_data": make_structure(["root"]),
        "session_id": trunk.session_id,
        "operations": [{"type": "add_object", "identity": {"id": "a", "type": "Thing", "name": "a"}}],
    })
    evolve_knowledge(runtime, {
        "json_data": make_structure(["root"]),
        "session_id": branch.session_id,
        "operations": [{"type": "add_object", "identity": {"id": "b", "type": "Thing", "name": "b"}}],
    })

    result = merge_branch(runtime, {
        "target_session_id": trunk.session_id,
        "source_session_id": branch.session_id,
    })
    assert result["merged"] is True
    assert "a" in result["serialized"]
    assert "b" in result["serialized"]

def test_merge_branch_missing_parameters():
    runtime = make_runtime()
    assert merge_branch(runtime, {})["error"] == "missing_parameter"
    assert merge_branch(runtime, {"target_session_id": "x"})["error"] == "missing_parameter"

def test_merge_branch_unknown_sessions():
    runtime = make_runtime()
    result = merge_branch(runtime, {"target_session_id": "ghost", "source_session_id": "ghost2"})
    assert result["error"] == "session_not_found"

def test_merge_branch_detects_conflicts():
    runtime = make_runtime()
    trunk = runtime.create_session(cks.parse(make_structure(["shared"])))
    tx = runtime.begin_transaction(trunk)
    runtime.commit_transaction(tx)
    branch = runtime.create_branch(trunk, version_id=trunk.version_history[0].version_id)

    # both edit the same object differently
    evolve_knowledge(runtime, {
        "json_data": make_structure(["shared"]),
        "session_id": trunk.session_id,
        "operations": [
            {"type": "remove_object", "object_id": "shared"},
            {"type": "add_object", "identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "trunk edit"}},
        ],
    })
    evolve_knowledge(runtime, {
        "json_data": make_structure(["shared"]),
        "session_id": branch.session_id,
        "operations": [
            {"type": "remove_object", "object_id": "shared"},
            {"type": "add_object", "identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "branch edit"}},
        ],
    })

    result = merge_branch(runtime, {
        "target_session_id": trunk.session_id,
        "source_session_id": branch.session_id,
    })
    assert result["merged"] is False
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["object_id"] == "shared"

def test_close_session_after_merge():
    runtime = make_runtime()
    trunk = runtime.create_session(cks.parse(make_structure(["root"])))
    tx = runtime.begin_transaction(trunk)
    runtime.commit_transaction(tx)
    branch = runtime.create_branch(trunk, version_id=trunk.version_history[0].version_id)

    evolve_knowledge(runtime, {
        "json_data": make_structure(["root"]),
        "session_id": trunk.session_id,
        "operations": [{"type": "add_object", "identity": {"id": "a", "type": "Thing", "name": "a"}}],
    })
    evolve_knowledge(runtime, {
        "json_data": make_structure(["root"]),
        "session_id": branch.session_id,
        "operations": [{"type": "add_object", "identity": {"id": "b", "type": "Thing", "name": "b"}}],
    })

    merge_branch(runtime, {
        "target_session_id": trunk.session_id,
        "source_session_id": branch.session_id,
    })
    close_result = close_session(runtime, {"session_id": branch.session_id})
    assert close_result["closed"] is True
    assert runtime.get_session(branch.session_id) is None

def test_create_branch_from_specific_version():
    runtime = make_runtime()
    trunk = runtime.create_session(cks.parse(make_structure(["root"])))
    tx = runtime.begin_transaction(trunk)
    runtime.commit_transaction(tx)
    initial_version_id = trunk.version_history[0].version_id

    evolve_knowledge(runtime, {
        "json_data": make_structure(["root"]),
        "session_id": trunk.session_id,
        "operations": [{"type": "add_object", "identity": {"id": "a", "type": "Thing", "name": "a"}}],
    })

    branch = create_branch(runtime, {"session_id": trunk.session_id, "version_id": initial_version_id})
    assert "session_id" in branch
    assert branch["parent_version_id"] == initial_version_id
    branch_session = runtime.get_session(branch["session_id"])
    assert branch_session is not None

def test_create_branch_invalid_version():
    runtime = make_runtime()
    trunk = runtime.create_session(cks.parse(make_structure(["root"])))
    result = create_branch(runtime, {"session_id": trunk.session_id, "version_id": "nonexistent"})
    assert "error" in result

def test_close_session_twice():
    runtime = make_runtime()
    session = runtime.create_session({})
    close_session(runtime, {"session_id": session.session_id})
    result = close_session(runtime, {"session_id": session.session_id})
    assert result["error"] == "session_not_found"