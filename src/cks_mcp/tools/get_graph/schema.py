"""Input schema definition for the get_graph tool."""

from __future__ import annotations

GET_GRAPH_SCHEMA = {
    "name": "get_graph",
    "description": (
        "Look up a Knowledge Graph previously registered under a memorable "
        "name via register_graph. Returns its session_id and metadata "
        "(description, tags, timestamps) so the caller can resume work "
        "against that session instead of rebuilding the graph from scratch. "
        "Returns {'found': false} if no graph is registered under that name."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The registered name of the graph to look up.",
            },
        },
        "required": ["name"],
    },
}
