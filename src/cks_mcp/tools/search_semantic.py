"""
search_semantic: semantic search over a session's Knowledge Structure.

Currently delegates to query_subgraph with the search query as a seed
description.  Future versions will use a vector index for true ANN search
and then expand the neighbourhood with query_subgraph.
"""

from typing import Any

from cks_runtime.runtime import Runtime
from cks_mcp.errors import missing_parameter, session_not_found


def search_semantic(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Search a session's Knowledge Structure semantically.

    Expects:
        session_id, query, optional top_k (default 3) and depth (default 1).
    """
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    query = arguments.get("query", "")
    top_k = int(arguments.get("top_k", 3))
    depth = int(arguments.get("depth", 1))

    # FUTURE: perform vector search to get seed_ids.
    # For now, require explicit seed_ids from the caller.
    seed_ids = arguments.get("seed_ids")
    if not seed_ids:
        return {
            "error": "not_implemented",
            "message": (
                "Vector index not available. Provide explicit 'seed_ids' "
                "to search the neighbourhood with query_subgraph."
            ),
        }

    # Use query_subgraph to expand around the seeds
    from cks_mcp.tools.query_subgraph import query_subgraph_tool

    subgraph_args = {
        "session_id": session_id,
        "seed_ids": seed_ids,
        "depth": depth,
        "max_objects": top_k + 5,  # allow some budget for relations
    }
    result = query_subgraph_tool(runtime, subgraph_args)
    if "error" in result:
        return result

    return {
        "status": "success",
        "matched_seeds": seed_ids,
        "subgraph": result["subgraph"],
        "meta": {
            "total_found_nodes": result["total_found_nodes"],
            "returned_nodes": result["returned_nodes"],
            "is_truncated": result["is_truncated"],
            "suggested_next_seed": result["suggested_next_seed"],
        },
    }