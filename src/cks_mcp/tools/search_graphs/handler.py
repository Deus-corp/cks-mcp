"""
search_graphs: free-text search over registered graphs (Memory Agent
gallery), matched against name/description/tags, so a caller can
discover a graph to resume with get_graph without already knowing its
exact registered name.

storage.list_graphs already supports an exact/substring `tag` filter
and `public_only`; this tool layers a case-insensitive `query`
substring match across name/description/tags on top, in Python --
list_graphs itself stays the single source of truth for what's
registered and for the public gating.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import empty_query


async def search_graphs(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    query = arguments.get("query")
    if not query or not query.strip():
        return empty_query()

    tag = arguments.get("tag") or None
    public_only = bool(arguments.get("public_only", False))
    team = arguments.get("team") or None

    candidates = await runtime.storage.list_graphs(tag, public_only, team=team)

    needle = query.strip().lower()
    matches = [
        graph
        for graph in candidates
        if needle in (graph.get("name") or "").lower()
        or needle in (graph.get("description") or "").lower()
        or needle in (graph.get("tags") or "").lower()
    ]

    return {"graphs": matches}
