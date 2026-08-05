"""Input schema definition for the check_graph_freshness tool."""

from __future__ import annotations

CHECK_GRAPH_FRESHNESS_SCHEMA = {
    "name": "check_graph_freshness",
    "description": (
        "Check whether a Knowledge Graph previously registered via "
        "register_graph is still fresh, by comparing its updated_at "
        "against the runtime's graph freshness TTL (the same TTL "
        "GraphFreshnessSweeper uses in the background). Returns "
        "{'fresh': true} or {'fresh': false, 'last_updated': ..., "
        "'ttl_days': ...}. Returns {'found': false} if no graph is "
        "registered under that name. This is a read-only check -- it "
        "does not refresh the graph itself."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The registered name of the graph to check.",
            },
        },
        "required": ["name"],
    },
}
