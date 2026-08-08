"""Input schema definitions for the query_subgraph tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

QUERY_SUBGRAPH_SCHEMA = {
    "name": "query_subgraph",
    "description": "Extract the local k‑hop neighbourhood around one or more seed ids "
    "from a session's current Knowledge Structure, or the whole graph if seed_ids "
    "is omitted. Returns a self‑contained "
    "subgraph (serialized) and metadata: total_found_nodes, returned_nodes, "
    "is_truncated, truncation_reason, suggested_next_seed. "
    "Use filters (include_relation_types, include_object_types) to narrow "
    "the traversal, and max_tokens/max_objects to cap the result. "
    "type_weights can prioritise certain object types when the budget "
    "forces truncation.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session whose Knowledge Structure to query.",
            },
            "seed_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of object ids to start traversal from. "
                "Optional — if omitted or empty, returns the whole graph "
                "(no traversal/depth/budget truncation applied).",
            },
            "depth": {
                "type": "integer",
                "description": "Maximum hops from any seed. Default 1.",
            },
            "include_relation_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional. Only traverse/include these relation types.",
            },
            "include_object_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional. Only include discovered objects of these types (seeds always kept).",
            },
            "max_tokens": {
                "type": "integer",
                "description": "Optional token budget (approx).",
            },
            "max_objects": {
                "type": "integer",
                "description": "Optional hard cap on total objects returned.",
            },
            "type_weights": {
                "type": "object",
                "description": "Optional mapping of object type to weight (float), used in budget ranking.",
            },
            "compact_mode": {
                "type": "boolean",
                "description": "If true, return a compact representation (nodes + edges) instead of full canonical JSON.",
            },
            "structure_filters": {
                "type": "object",
                "description": (
                    "Optional. AND-filter applied to non-relation objects after extraction: "
                    "only objects whose 'structure' dict contains ALL key=value pairs survive. "
                    "Seed objects are always kept regardless. Relations are retained when "
                    "both their participants survive the filter. "
                    'Example: {"status": "active", "domain": "biology"}.'
                ),
            },
        },
        "required": ["session_id"],
    },
}
