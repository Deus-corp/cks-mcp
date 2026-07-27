"""
visualize_graph: export a subgraph as a Mermaid diagram.

Claude Desktop renders Mermaid natively, so the user sees the graph
visually. Use this after query_subgraph to show the structure.
"""

from __future__ import annotations
from typing import Any

from cks_runtime.runtime import Runtime
from cks_mcp.errors import missing_parameter, session_not_found


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

    if seed_ids:
        from cks_mcp.tools.query_subgraph import query_subgraph_tool
        subgraph_result = query_subgraph_tool(runtime, {
            "session_id": session_id,
            "seed_ids": seed_ids,
            "depth": depth,
            "max_objects": max_objects,
        })
        if "error" in subgraph_result:
            return subgraph_result
        objects_to_show = subgraph_result.get("subgraph", {})
        if isinstance(objects_to_show, dict) and "nodes" in objects_to_show:
            nodes = objects_to_show["nodes"]
            edges = objects_to_show["edges"]
        else:
            # Full canonical JSON was returned; parse it
            import cks
            structure = cks.parse(objects_to_show)
            nodes = [
                {"id": obj.identity.id, "type": obj.identity.type, "name": obj.identity.name}
                for obj in structure.objects if not hasattr(obj, 'participants')
            ]
            edges = [
                {"source": rel.participants[0], "target": rel.participants[1], "type": rel.relation_type}
                for rel in structure.relations() if len(rel.participants) >= 2
            ]
    else:
        from cks.core import CanonicalRelation
        structure = session.knowledge_structure
        nodes = [
            {"id": obj.identity.id, "type": obj.identity.type, "name": obj.identity.name}
            for obj in structure.objects if not isinstance(obj, CanonicalRelation)
        ]
        edges = [
            {"source": rel.participants[0], "target": rel.participants[1], "type": rel.relation_type}
            for rel in structure.relations() if len(rel.participants) >= 2
        ]

    if not nodes:
        return {"mermaid": "graph TD\n    empty[Empty graph]"}

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

    return {"mermaid": "\n".join(lines)}