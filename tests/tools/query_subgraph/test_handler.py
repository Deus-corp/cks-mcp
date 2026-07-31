"""Unit tests for the query_subgraph MCP tool."""

from __future__ import annotations

import pytest

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)

pytestmark = pytest.mark.asyncio


async def test_query_subgraph_basic():
    """End-to-end test: create a session and extract a subgraph."""
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter

    from cks_mcp.tools.query_subgraph.handler import query_subgraph_tool

    runtime = Runtime(core=CksCoreAdapter())

    from cks import parse
    structure = parse(
        '{"objects": ['
        '{"identity": {"id": "A", "type": "Node", "name": "a"}, "structure": {}},'
        '{"identity": {"id": "B", "type": "Node", "name": "b"}, "structure": {}},'
        '{"identity": {"id": "C", "type": "Node", "name": "c"}, "structure": {}},'
        '{"identity": {"id": "r1", "type": "Relation", "name": "r1"}, "structure": {"participants": ["A", "B"], "relation_type": "links"}},'
        '{"identity": {"id": "r2", "type": "Relation", "name": "r2"}, "structure": {"participants": ["B", "C"], "relation_type": "links"}}'
        ']}'
    )
    session = await runtime.create_session(structure)

    result = await query_subgraph_tool(runtime, {
        "session_id": session.session_id,
        "seed_ids": ["A"],
        "depth": 1
    })

    assert "subgraph" in result
    assert "total_found_nodes" in result
    assert result["total_found_nodes"] == 2  # A, B
    assert result["is_truncated"] == False
