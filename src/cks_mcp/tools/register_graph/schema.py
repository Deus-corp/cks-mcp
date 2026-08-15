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
                    "Whether this graph is discoverable in the gallery by other "
                    "callers, via list_graphs(public_only=true) or search_graphs. "
                    "Defaults to false (private, discoverable only by name via "
                    "get_graph)."
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
