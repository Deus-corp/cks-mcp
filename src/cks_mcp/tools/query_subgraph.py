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
    compact_mode = arguments.get("compact_mode", False)

    # Optional filters and budget
    include_relation_types = arguments.get("include_relation_types")
    include_object_types = arguments.get("include_object_types")
    max_tokens = arguments.get("max_tokens")
    max_objects = arguments.get("max_objects")
    type_weights = arguments.get("type_weights")

    # Read‑only execution
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
        compact_mode=compact_mode,
    )

    result = runtime.executor.execute(op, session)

    if result.status.value == "failed":
        return {"error": f"query_subgraph failed: {result.error}"}

    subgraph_result = result.payload  # cks-core SubgraphResult

    if compact_mode:
        from cks.core import CanonicalRelation
        nodes = []
        edges = []
        for obj in subgraph_result.structure.objects:
            if isinstance(obj, CanonicalRelation):
                edges.append({
                    "source": obj.participants[0] if len(obj.participants) > 0 else None,
                    "target": obj.participants[1] if len(obj.participants) > 1 else None,
                    "type": obj.relation_type,
                })
            else:
                nodes.append({
                    "id": obj.identity.id,
                    "type": obj.identity.type,
                    "name": obj.identity.name,
                    "props": dict(obj.structure),
                })

        return {
            "session_id": session_id,
            "subgraph": {"nodes": nodes, "edges": edges},
            "subgraph_root_hash": subgraph_result.structure.root_hash,
            "total_found_nodes": subgraph_result.total_found_nodes,
            "returned_nodes": subgraph_result.returned_nodes,
            "is_truncated": subgraph_result.is_truncated,
            "truncation_reason": subgraph_result.truncation_reason,
            "suggested_next_seed": subgraph_result.suggested_next_seed,
        }

    # Full serialized mode
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