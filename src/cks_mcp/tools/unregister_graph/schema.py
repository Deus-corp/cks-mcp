"""Input schema definition for the unregister_graph tool."""

from __future__ import annotations

UNREGISTER_GRAPH_SCHEMA = {
    "name": "unregister_graph",
    "description": (
        "Remove a graph previously registered via register_graph from the "
        "registry (Gallery), so it no longer shows up in list_graphs/"
        "search_graphs or resolves via get_graph. This only removes the "
        "name -> session_id mapping -- the underlying session and its "
        "Knowledge Structure are left untouched and remain addressable by "
        "session id (e.g. via clone_graph or query_subgraph)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The registered name of the graph to remove from the registry.",
            },
        },
        "required": ["name"],
    },
}