"""Input schema definition for the clone_graph tool."""

from __future__ import annotations

CLONE_GRAPH_SCHEMA = {
    "name": "clone_graph",
    "description": (
        "Create a new session containing a copy of an existing registered "
        "graph (or any live session), so it can be explored, modified, or "
        "extended without touching the original. Read-only with respect to "
        "the source: the source session/graph is never modified. Either "
        "'graph_name' or 'source_session_id' must be given (the latter "
        "takes precedence if both are). By default the clone lands in a "
        "brand-new session; pass 'target_session_id' to import it into an "
        "existing open session instead, merging in only the objects/"
        "relations not already present there."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "graph_name": {
                "type": "string",
                "description": (
                    "Registered graph name to clone (see register_graph/"
                    "list_graphs). Either graph_name or source_session_id "
                    "is required."
                ),
            },
            "source_session_id": {
                "type": "string",
                "description": (
                    "Session id of the graph to clone. Takes precedence "
                    "over graph_name if both are provided."
                ),
            },
            "target_session_id": {
                "type": "string",
                "description": (
                    "Optional existing, open session to import the clone "
                    "into. If omitted, a new session is created instead."
                ),
            },
            "copy_name": {
                "type": "string",
                "description": (
                    "Optional name to register the clone under via "
                    "register_graph. Only applies when a new session is "
                    "created (i.e. target_session_id is omitted)."
                ),
            },
            "description": {
                "type": "string",
                "description": (
                    "Optional description to register the clone with, "
                    "used only together with copy_name. Defaults to "
                    "mentioning the source graph/session."
                ),
            },
            "tags": {
                "type": "string",
                "description": (
                    "Optional comma-separated tags to register the clone "
                    "with, used only together with copy_name."
                ),
            },
            "public": {
                "type": "boolean",
                "description": (
                    "Whether the clone should be discoverable via "
                    "list_graphs(public_only=True)/search_graphs, used "
                    "only together with copy_name. Defaults to false."
                ),
            },
        },
        "required": [],
    },
}
