"""Input schema for the compare_graphs tool."""

from __future__ import annotations

COMPARE_GRAPHS_SCHEMA = {
    "name": "compare_graphs",
    "description": "Compare two graphs or sessions and return shared objects, "
    "differences, and only-in-one-side ids. Read-only -- never modifies "
    "either source. Each side is given either by registry name "
    "('graph_a_name'/'graph_b_name') or directly by session id "
    "('graph_a_session_id'/'graph_b_session_id', which takes precedence "
    "over the name when both are given).",
    "inputSchema": {
        "type": "object",
        "properties": {
            "graph_a_name": {
                "type": "string",
                "description": "Registered graph name for side A. Either this or "
                "graph_a_session_id is required.",
            },
            "graph_a_session_id": {
                "type": "string",
                "description": "Session id for side A. Takes precedence over graph_a_name.",
            },
            "graph_b_name": {
                "type": "string",
                "description": "Registered graph name for side B. Either this or "
                "graph_b_session_id is required.",
            },
            "graph_b_session_id": {
                "type": "string",
                "description": "Session id for side B. Takes precedence over graph_b_name.",
            },
            "include_relations": {
                "type": "boolean",
                "default": True,
                "description": "Include relation ids/differences in the comparison, not "
                "just plain objects.",
            },
        },
        "required": [],
    },
}