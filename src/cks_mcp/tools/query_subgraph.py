"""
query_subgraph: extract a k‑hop neighbourhood from a session's current
Knowledge Structure, with optional budget and filters.

Read‑only – never creates a transaction or version.
"""

from __future__ import annotations
from typing import Any

from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import QuerySubgraphOperation
from cks_mcp.errors import missing_parameter, session_not_found


def query_subgraph_tool(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """MCP tool handler for query_subgraph."""
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    seed_ids = arguments.get("seed_ids")
    if not seed_ids:
        return missing_parameter("seed_ids")

    depth = int(arguments.get("depth", 1))

    # Optional filters and budget
    include_relation_types = arguments.get("include_relation_types")
    include_object_types = arguments.get("include_object_types")
    max_tokens = arguments.get("max_tokens")
    max_objects = arguments.get("max_objects")
    type_weights = arguments.get("type_weights")

    # Read‑only execution, exactly like explain_knowledge with session_id
    op = QuerySubgraphOperation(
        "query_subgraph",
        knowledge_structure=session.knowledge_structure,
        seed_ids=seed_ids,
        depth=depth,
        include_relation_types=include_relation_types,
        include_object_types=include_object_types,
        max_tokens=max_tokens,
        max_objects=max_objects,
        type_weights=type_weights,
    )

    result = runtime.executor.execute(op, session)

    if result.status.value == "failed":
        return {"error": f"query_subgraph failed: {result.error}"}

    subgraph_result = result.payload  # cks-core SubgraphResult

    # Serialize the extracted subgraph structure
    subgraph_serialized = runtime.core_bridge.serialize(subgraph_result.structure)

    return {
        "session_id": session_id,
        "subgraph": subgraph_serialized,
        "subgraph_root_hash": subgraph_result.structure.root_hash,
        "total_found_nodes": subgraph_result.total_found_nodes,
        "returned_nodes": subgraph_result.returned_nodes,
        "is_truncated": subgraph_result.is_truncated,
        "truncation_reason": subgraph_result.truncation_reason,
        "suggested_next_seed": subgraph_result.suggested_next_seed,
    }