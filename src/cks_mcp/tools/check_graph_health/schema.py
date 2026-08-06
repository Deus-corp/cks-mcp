"""Input schema definition for the check_graph_health tool."""

from __future__ import annotations

CHECK_GRAPH_HEALTH_SCHEMA = {
    "name": "check_graph_health",
    "description": (
        "Compute an aggregate health score (0.0-1.0) for a registered "
        "graph (register_graph), combining several existing read-only "
        "checks into one weighted metric: version freshness "
        "(check_component_versions, weight 0.3), TTL freshness "
        "(check_graph_freshness, weight 0.1), contradictions "
        "(detect_contradictions, weight 0.3), verification coverage -- "
        "the share of VerificationRecord objects in the graph's session "
        "checked within the last 30 days (weight 0.2), and dead-lettered "
        "conflict tasks for the graph's session "
        "(list_dead_lettered_conflicts, weight 0.1). Returns "
        "{'name', 'session_id', 'health_score', 'metrics': {...}, "
        "'timestamp'}. Returns {'found': false} if no graph is registered "
        "under that name. Read-only -- does not modify the graph, "
        "does not apply any fixes."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "The registered name of the graph to check, e.g. "
                    "'cks-ecosystem'."
                ),
            },
        },
        "required": ["name"],
    },
}
