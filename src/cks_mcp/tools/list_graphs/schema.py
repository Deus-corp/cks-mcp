"""Input schema definition for the list_graphs tool."""

from __future__ import annotations

LIST_GRAPHS_SCHEMA = {
    "name": "list_graphs",
    "description": (
        "List every Knowledge Graph registered via register_graph, most "
        "recently updated first. Optionally filter to graphs whose tags "
        "contain a given substring. Use this to browse what's available "
        "before resuming a specific one with get_graph."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "tag": {
                "type": "string",
                "description": "Optional tag (or tag substring) to filter the results by.",
            },
            "public_only": {
                "type": "boolean",
                "description": (
                    "If true, only return graphs registered with public=true "
                    "(the gallery). Defaults to false (returns every graph, "
                    "public and private)."
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
        "required": [],
    },
}