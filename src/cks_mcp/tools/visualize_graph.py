"""
visualize_graph: export a subgraph as a Mermaid diagram.
"""

from typing import Any

from cks_runtime.runtime import Runtime
from cks_mcp.errors import missing_parameter, session_not_found
from cks_mcp.tools.query_subgraph import query_subgraph_tool


def visualize_graph(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Export a subgraph as a Mermaid diagram."""
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    # Reuse query_subgraph to get the data in compact mode
    seed_ids = arguments.get("seed_ids")
    if not seed_ids:
        # Default to all objects if no seeds specified
        seed_ids = [
            obj.identity.id
            for obj in session.knowledge_structure.objects
            if not hasattr(obj, 'participants')  # exclude relations
        ]

    depth = int(arguments.get("depth", 1))
    compact_mode = True

    subgraph_args = {
        "session_id": session_id,
        "seed_ids": seed_ids,
        "depth": depth,
        "compact_mode": compact_mode,
        "max_objects": arguments.get("max_objects", 20),
    }
    result = query_subgraph_tool(runtime, subgraph_args)
    if "error" in result:
        return result

    # Build Mermaid diagram
    lines = ["graph TD"]
    node_ids = set()
    for node in result.get("subgraph", {}).get("nodes", []):
        nid = node["id"]
        node_ids.add(nid)
        label = node.get("name", nid)
        # Escape quotes in label
        label = label.replace('"', '\\"')
        lines.append(f'    {nid}["{label} ({node["type"]})"]')

    for edge in result.get("subgraph", {}).get("edges", []):
        src = edge["source"]
        tgt = edge["target"]
        if src in node_ids and tgt in node_ids:
            label = edge.get("type", "")
            lines.append(f'    {src} -->|"{label}"| {tgt}')

    mermaid = "\n".join(lines)

    return {
        "mermaid": mermaid,
        "total_found_nodes": result.get("total_found_nodes", 0),
        "returned_nodes": result.get("returned_nodes", 0),
        "is_truncated": result.get("is_truncated", False),
    }