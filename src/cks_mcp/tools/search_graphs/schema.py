"""Input schema definition for the search_graphs tool."""

from __future__ import annotations

SEARCH_GRAPHS_SCHEMA = {
    "name": "search_graphs",
    "description": (
        "Search registered Knowledge Graphs (Memory Agent gallery) by a "
        "free-text query matched against name, description, and tags -- "
        "case-insensitive substring match. Optionally narrow further by "
        "an exact tag or restrict to public graphs only. Use this to "
        "discover a graph to resume with get_graph when you don't "
        "already know its exact name (for that, use get_graph directly)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Free-text search term, matched (case-insensitively) "
                    "against each graph's name, description, and tags."
                ),
            },
            "tag": {
                "type": "string",
                "description": "Optional tag (or tag substring) to further filter the results by.",
            },
            "public_only": {
                "type": "boolean",
                "description": (
                    "If true, only return graphs registered with public=true. "
                    "Defaults to false."
                ),
            },
            "team": {
                "type": "string",
                "description": (
                    "Optional team namespace. When given (and public_only is "
                    "false), also includes graphs registered with "
                    "visibility='team' and this same team, in addition to "
                    "public graphs. There is no authentication behind this -- "
                    "it's a caller-supplied namespace, like the registry "
                    "name itself."
                ),
            },
        },
        "required": ["query"],
    },
}