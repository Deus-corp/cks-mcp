"""
search_semantic: semantic search over a session's Knowledge Structure.

Uses vector embeddings stored by cks-runtime's OutboxEmbeddingWorker
to find relevant object IDs, then expands them with query_subgraph.
"""

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import empty_query, missing_parameter, session_not_found
from cks_mcp.tools.query_subgraph import query_subgraph_tool


def search_semantic(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    query = arguments.get("query", "")
    if not query or not query.strip():
        return empty_query()

    top_k = int(arguments.get("top_k", 3))
    depth = int(arguments.get("depth", 1))
    min_score = float(arguments.get("min_score", 0.0))

    # Try to use vector search if storage supports it
    seed_ids = arguments.get("seed_ids")
    # Populated only when seed_ids come from vector search below --
    # caller-supplied seed_ids have no similarity score to report.
    scores: dict[str, float] | None = None
    # Set only if vector search itself raised, so a real failure can
    # be told apart from a genuine no-match.
    search_error: str | None = None
    if not seed_ids and hasattr(runtime.storage, "search_embeddings"):
        try:
            # Must be the exact same client instance used to index
            # objects (Runtime.embedding_client), or the query vector
            # lives in a different embedding space than what's stored
            # and every similarity score is meaningless.
            query_embedding = runtime.embedding_client.embed_batch(
                [query], normalize=True
            )[0]
            results = runtime.storage.search_embeddings(
                query_embedding,
                session_id,
                top_k=top_k * 2,
            )
            scores_by_id = {oid: sim for oid, sim in results}
            seed_ids = [oid for oid, _ in results]
            if seed_ids:
                # Filter to those actually in the current structure
                # and exclude relation objects
                seed_ids = [
                    sid
                    for sid in seed_ids
                    if (obj := session.knowledge_structure.get(sid)) is not None
                    and getattr(obj.identity, "type", "") != "Relation"
                ][:top_k]
                scores = {sid: scores_by_id[sid] for sid in seed_ids}
                # Filter by minimum relevance score
                if min_score > 0.0:
                    seed_ids = [
                        sid for sid in seed_ids if scores.get(sid, 0.0) >= min_score
                    ]
                    scores = {sid: scores_by_id[sid] for sid in seed_ids}
        except Exception as e:
            seed_ids = None
            scores = None
            search_error = str(e)

    if not seed_ids:
        message = (
            "No matching objects found. Provide explicit 'seed_ids' "
            "or ensure embeddings have been generated for this session."
        )
        if search_error is not None:
            message += f" (semantic search failed: {search_error})"
        return {
            "error": "not_found",
            "message": message,
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

    response: dict[str, Any] = {
        "status": "success",
        "matched_seeds": seed_ids,
        "subgraph": result["subgraph"],
        "meta": {
            "total_found_nodes": result["total_found_nodes"],
            "returned_nodes": result["returned_nodes"],
            "is_truncated": result["is_truncated"],
            "suggested_next_seed": result["suggested_next_seed"],
        },
        "min_score": min_score,
    }
    if scores is not None:
        response["scores"] = scores
    return response
