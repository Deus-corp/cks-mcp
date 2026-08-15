"""Input schema for the link_graphs tool."""

from __future__ import annotations

LINK_GRAPHS_SCHEMA = {
    "name": "link_graphs",
    "description": "Create a cross-graph relation between an object in graph A and "
    "an object in graph B. The relation is written to BOTH source graphs -- "
    "each session gets a new version containing the relation, so it is "
    "visible/queryable from either side. Fails if either object is missing, "
    "or if a relation with the derived id already exists in either graph.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "graph_a_name": {"type": "string"},
            "graph_a_session_id": {"type": "string"},
            "graph_b_name": {"type": "string"},
            "graph_b_session_id": {"type": "string"},
            "object_a_id": {"type": "string", "description": "Object id in graph A."},
            "object_b_id": {"type": "string", "description": "Object id in graph B."},
            "relation_type": {
                "type": "string",
                "description": "Relation type, e.g. 'depends_on' or 'references'.",
            },
            "relation_name": {
                "type": "string",
                "description": "Optional display name for the relation object. "
                "Defaults to '<relation_type>: <object_a_id> -> <object_b_id>'.",
            },
        },
        "required": ["object_a_id", "object_b_id", "relation_type"],
    },
}