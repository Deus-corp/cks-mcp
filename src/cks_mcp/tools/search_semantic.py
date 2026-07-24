"""
search_semantic: semantic search over a session's Knowledge Structure.

Uses vector embeddings stored by cks-runtime's OutboxEmbeddingWorker
to find relevant object IDs, then expands them with query_subgraph.
"""

from typing import Any

from cks_runtime.runtime import Runtime
from cks_runtime.embedding.client import StubEmbeddingClient
from cks_mcp.errors import missing_parameter, session_not_found
from cks_mcp.tools.query_subgraph import query_subgraph_tool


def search_semantic(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    query = arguments.get("query", "")
    top_k = int(arguments.get("top_k", 3))
    depth = int(arguments.get("depth", 1))

    # Try to use vector search if storage supports it
    seed_ids = arguments.get("seed_ids")
    if not seed_ids and hasattr(runtime.storage, "search_embeddings"):
        try:
            # Use runtime's embedding client if available, else fallback to stub
            client = getattr(runtime, '_embedding_client', None) or StubEmbeddingClient()
            query_embedding = client.embed_batch([query])[0]
            seed_ids = runtime.storage.search_embeddings(
                query_embedding,
                session_id,
                top_k=top_k * 2,
            )
            if seed_ids:
                # Filter to those actually in the current structure
                # and exclude relation objects
                seed_ids = [
                    sid for sid in seed_ids
                    if (obj := session.knowledge_structure.get(sid)) is not None
                    and getattr(obj.identity, 'type', '') != 'Relation'
                ][:top_k]
        except Exception:
            seed_ids = None

    if not seed_ids:
        return {
            "error": "not_found",
            "message": (
                "No matching objects found. Provide explicit 'seed_ids' "
                "or ensure embeddings have been generated for this session."
            ),
        }

    # Use query_subgraph to expand around the seeds
    subgraph_args = {
        "session_id": session_id,
        "seed_ids": seed_ids,
        "depth": depth,
        "max_objects": top_k + 5,
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