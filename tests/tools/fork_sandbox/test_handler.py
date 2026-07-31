"""Unit tests for the fork_sandbox MCP tool."""

from __future__ import annotations

import pytest

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)

pytestmark = pytest.mark.asyncio


def _real_runtime():
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter
    return Runtime(core=CksCoreAdapter())



async def test_fork_sandbox_no_operations():
    from cks import parse

    from cks_mcp.tools.fork_sandbox.handler import fork_sandbox

    runtime = _real_runtime()
    structure = parse(
        '{"objects":[{"identity":{"id":"obj-1","type":"Concept","name":"A"},"structure":{}}]}'
    )
    parent = await runtime.create_session(structure)
    result = await fork_sandbox(runtime, {
        "session_id": parent.session_id,
        "hypothesis": "test sandbox"
    })
    assert "sandbox_session_id" in result
    assert result["parent_session_id"] == parent.session_id
    assert result["operations_applied"] == 0
    assert result["diff_from_fork_point"]["summary"]["added_objects"] == 0
    assert result["diff_from_fork_point"]["summary"]["removed_objects"] == 0
    assert parent.knowledge_structure is not None
    assert len(parent.knowledge_structure.objects) == 1


async def test_fork_sandbox_with_valid_operations():
    from cks import parse

    from cks_mcp.tools.fork_sandbox.handler import fork_sandbox

    runtime = _real_runtime()
    structure = parse(
        '{"objects":[{"identity":{"id":"obj-1","type":"Concept","name":"A"},"structure":{}}]}'
    )
    parent = await runtime.create_session(structure)
    result = await fork_sandbox(runtime, {
        "session_id": parent.session_id,
        "hypothesis": "add object B",
        "operations": [
            {"type": "add_object", "identity": {"id": "obj-2", "type": "Concept", "name": "B"}, "structure": {}}
        ]
    })
    assert result["operations_applied"] == 1
    assert result["diff_from_fork_point"]["summary"]["added_objects"] == 1
    assert len(parent.knowledge_structure.objects) == 1
    sandbox = runtime.get_session(result["sandbox_session_id"])
    assert sandbox is not None
    assert len(sandbox.knowledge_structure.objects) == 2


async def test_fork_sandbox_invalid_operations():
    from cks import parse

    from cks_mcp.tools.fork_sandbox.handler import fork_sandbox

    runtime = _real_runtime()
    structure = parse(
        '{"objects":[{"identity":{"id":"obj-1","type":"Concept","name":"A"},"structure":{}}]}'
    )
    parent = await runtime.create_session(structure)
    result = await fork_sandbox(runtime, {
        "session_id": parent.session_id,
        "operations": [{"type": "add_object", "identity": {"id": "obj-1", "type": "Concept", "name": "duplicate"}}]
    })
    assert "error" in result
    assert result["error"] == "evolution_failed"
    sandbox_id = result.get("sandbox_session_id")
    if sandbox_id:
        assert runtime.get_session(sandbox_id) is None
    assert len(parent.knowledge_structure.objects) == 1


async def test_fork_sandbox_missing_session_id():
    from cks_mcp.tools.fork_sandbox.handler import fork_sandbox

    runtime = _real_runtime()
    result = await fork_sandbox(runtime, {})
    assert result["error"] == "missing_parameter"
