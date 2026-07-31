"""Input schema definitions for the visualize_graph tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

VISUALIZE_GRAPH_SCHEMA = {
    "name": "visualize_graph",
    "description": "Export a subgraph as a Mermaid diagram. Many MCP clients render "
    "Mermaid natively; if yours doesn't, the raw Mermaid text is still "
    "useful as structured output. Use this after query_subgraph to show "
    "the structure.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session to visualize.",
            },
            "seed_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional. Object IDs to start from. Defaults to all objects.",
            },
            "depth": {
                "type": "integer",
                "description": "How many hops to expand. Default 1.",
            },
            "max_objects": {
                "type": "integer",
                "description": "Max objects to include. Default 20.",
            },
        },
        "required": ["session_id"],
    },
}
