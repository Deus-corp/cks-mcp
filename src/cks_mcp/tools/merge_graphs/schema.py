"""Input schema for the merge_graphs tool."""

from __future__ import annotations

MERGE_GRAPHS_SCHEMA = {
    "name": "merge_graphs",
    "description": "Merge two graphs into a brand-new session using a three-way "
    "merge (cks.KnowledgeStructure.merge). Neither source session is ever "
    "modified. If no common ancestor is known, an empty structure is used "
    "as the merge base -- fine for independently-built graphs, but it means "
    "any identity present (and differing) on both sides is reported as a "
    "conflict rather than auto-merged, since there is no base value to "
    "compare against. On conflict, returns {'merged': false, 'conflicts': "
    "[...]} and creates nothing; retry with a 'resolutions' argument "
    "mapping each conflicting object_id to 'branch_a', 'branch_b', null "
    "(drop it), or a complete object definition.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "graph_a_name": {"type": "string"},
            "graph_a_session_id": {"type": "string"},
            "graph_b_name": {"type": "string"},
            "graph_b_session_id": {"type": "string"},
            "base_graph_name": {
                "type": "string",
                "description": "Optional common ancestor graph, by registry name.",
            },
            "base_session_id": {
                "type": "string",
                "description": "Optional common ancestor session id. Takes precedence "
                "over base_graph_name.",
            },
            "resolutions": {
                "type": "object",
                "description": "Optional per-object conflict resolution mapping. Keys "
                "are object ids. Values: 'branch_a' (take graph A's version), "
                "'branch_b' (take graph B's version), null (drop the object), or a "
                "complete object definition to use as the merged result.",
            },
            "register_as": {
                "type": "string",
                "description": "Optional name to register the merged graph under, "
                "same as register_graph's 'name'.",
            },
        },
        "required": [],
    },
}