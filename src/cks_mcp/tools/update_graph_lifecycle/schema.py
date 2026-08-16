"""Input schema definition for the update_graph_lifecycle tool."""

from __future__ import annotations

UPDATE_GRAPH_LIFECYCLE_SCHEMA = {
    "name": "update_graph_lifecycle",
    "description": (
        "Transition a registered graph's lifecycle state -- one of "
        "'draft', 'published', 'active', 'stale', 'under_review', "
        "'archived' -- so the graph's maturity/status is visible "
        "alongside its register_graph entry (surfaced by get_graph / "
        "list_graphs as 'lifecycle_state'). Only registered graphs are "
        "supported; unregistered sessions have no lifecycle state. "
        "Not every transition is allowed -- e.g. a 'draft' graph can "
        "become 'published' or 'archived' but not 'active' directly. "
        "Requesting a disallowed transition returns "
        "{'error': 'invalid_state_transition', 'allowed': [...]} "
        "without changing anything. On success, returns "
        "{'updated': true, 'name': ..., 'previous_state': ..., "
        "'new_state': ...}."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The registered name of the graph to transition.",
            },
            "state": {
                "type": "string",
                "enum": [
                    "draft",
                    "published",
                    "active",
                    "stale",
                    "under_review",
                    "archived",
                ],
                "description": "The lifecycle state to transition the graph to.",
            },
        },
        "required": ["name", "state"],
    },
}
