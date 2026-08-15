"""Input schema definition for the register_graph tool."""

from __future__ import annotations

REGISTER_GRAPH_SCHEMA = {
    "name": "register_graph",
    "description": (
        "Register (or update) a memorable name for an existing session's "
        "Knowledge Graph, so it -- or another LLM/person -- can find and "
        "reuse it later via get_graph/list_graphs instead of rebuilding "
        "the graph from scratch. Registering an already-used name replaces "
        "its existing entry (last write wins)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "A short, memorable, unique name for this graph (the registry key).",
            },
            "session_id": {
                "type": "string",
                "description": "The session id of the Knowledge Graph to register under this name.",
            },
            "description": {
                "type": "string",
                "description": "Optional free-text description of what this graph contains.",
            },
            "tags": {
                "type": "string",
                "description": "Optional comma-separated tags, usable as a filter in list_graphs.",
            },
            "public": {
                "type": "boolean",
                "description": (
                    "Legacy shorthand for visibility='public' (true) / "
                    "visibility='private' (false). Ignored if `visibility` is "
                    "also given. Defaults to false (private, discoverable only "
                    "by name via get_graph)."
                ),
            },
            "visibility": {
                "type": "string",
                "enum": ["private", "team", "public"],
                "description": (
                    "Who can discover this graph via list_graphs/search_graphs "
                    "(get_graph by exact name always works regardless). "
                    "'private' (default): nobody but a caller who already knows "
                    "the name. 'team': callers who pass this same `team` name to "
                    "list_graphs/search_graphs. 'public': everyone, via "
                    "list_graphs(public_only=true) or search_graphs. Takes "
                    "precedence over the legacy `public` boolean when given."
                ),
            },
            "team": {
                "type": "string",
                "description": (
                    "Required when visibility='team': the team namespace this "
                    "graph is scoped to. There is no authentication behind this "
                    "-- it's a caller-supplied namespace, like the registry name "
                    "itself, so treat it as shared-secret-ish rather than a real "
                    "access control boundary."
                ),
            },
            "source_graph_name": {
                "type": "string",
                "description": (
                    "Optional: the registered name of the graph this one was "
                    "cloned/forked from (clone lineage), so the gallery can show "
                    "'forked from X' and link back to the original. Normally set "
                    "automatically by clone_graph(copy_name=...) rather than "
                    "passed directly. Omitting it leaves any existing lineage on "
                    "this name untouched (it does not clear it)."
                ),
            },
        },
        "required": ["name", "session_id"],
    },
}