"""Input schema definition for the check_component_versions tool."""

from __future__ import annotations

CHECK_COMPONENT_VERSIONS_SCHEMA = {
    "name": "check_component_versions",
    "description": (
        "Check whether a registered ecosystem graph (register_graph) is "
        "up to date with the real code it describes. Looks up the graph "
        "by name via get_graph, scans its session for 'Component' "
        "objects that carry a 'version' field, resolves each one's "
        "GitHub repository (by known component name or a 'repo_url' "
        "field in its structure), fetches that repository's "
        "_version.py from the GitHub raw API, and compares the two "
        "version strings. Returns "
        "{'found': true, 'components': [{'component': ..., "
        "'graph_version': ..., 'actual_version': ..., 'status': "
        "'up_to_date' | 'outdated' | 'ahead' | 'unknown_repo' | "
        "'fetch_failed'}, ...]}. Returns {'found': false} if no graph "
        "is registered under that name. Read-only -- never modifies "
        "the graph or session."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "The registered name of the graph to check, e.g. "
                    "'cks-ecosystem'."
                ),
            },
        },
        "required": ["name"],
    },
}