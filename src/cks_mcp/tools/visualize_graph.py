"""
visualize_graph: export a subgraph as a Mermaid diagram.

Claude Desktop renders Mermaid natively, so the user sees the graph
visually. Use this after query_subgraph to show the structure.
"""

from __future__ import annotations
from typing import Any

from cks_runtime.runtime import Runtime
from cks_mcp.errors import missing_parameter, session_not_found
from cks_mcp.tools.query_subgraph import query_subgraph_tool


def visualize_graph(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Export a session's Knowledge Structure or a subgraph as Mermaid."""
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    seed_ids = arguments.get("seed_ids")
    depth = int(arguments.get("depth", 1))
    max_objects = int(arguments.get("max_objects", 20))

    # Always use query_subgraph in compact mode for consistent handling
    # of max_objects, metadata, and node/edge extraction.
    if seed_ids is None:
        # When no seeds are given, treat every non-relation object as a seed
        # with depth=0, so max_objects limits total nodes in a predictable way.
        from cks.core import CanonicalRelation
        seed_ids = [
            obj.identity.id
            for obj in session.knowledge_structure.objects
            if not isinstance(obj, CanonicalRelation)
        ]
        depth = 0

    subgraph_result = query_subgraph_tool(runtime, {
        "session_id": session_id,
        "seed_ids": seed_ids,
        "depth": depth,
        "max_objects": max_objects,
        "compact_mode": True,
    })

    if "error" in subgraph_result:
        return subgraph_result

    # subgraph_result["subgraph"] is guaranteed to have "nodes" and "edges"
    # because compact_mode=True was requested.
    subgraph = subgraph_result["subgraph"]
    nodes = subgraph.get("nodes", [])
    edges = subgraph.get("edges", [])

    if not nodes:
        return {
            "mermaid": "graph TD\n    empty[Empty graph]",
            "total_found_nodes": 0,
            "returned_nodes": 0,
            "is_truncated": False,
        }

    # Build safe aliases for every node, so that IDs containing spaces,
    # colons, brackets, or hyphens don't break Mermaid syntax.
    safe_alias: dict[str, str] = {}
    for i, node in enumerate(nodes):
        safe_alias[node["id"]] = f"n{i}"

    lines = ["graph TD"]
    for node in nodes:
        alias = safe_alias[node["id"]]
        label = f"{node['name']} ({node['type']})".replace('"', '#quot;')
        lines.append(f'    {alias}["{label}"]')

    for edge in edges:
        src = safe_alias.get(edge["source"])
        tgt = safe_alias.get(edge["target"])
        if src is None or tgt is None:
            continue
        rel_type = edge["type"].replace('"', '#quot;')
        lines.append(f'    {src} -->|"{rel_type}"| {tgt}')

    return {
        "mermaid": "\n".join(lines),
        "total_found_nodes": subgraph_result.get("total_found_nodes", len(nodes)),
        "returned_nodes": subgraph_result.get("returned_nodes", len(nodes)),
        "is_truncated": subgraph_result.get("is_truncated", False),
    }