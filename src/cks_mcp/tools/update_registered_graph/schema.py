"""Input schema definition for the update_registered_graph tool."""

from __future__ import annotations

UPDATE_REGISTERED_GRAPH_SCHEMA = {
    "name": "update_registered_graph",
    "description": (
        "Bring a registered ecosystem graph (register_graph) back in sync "
        "with the real code it describes. First calls check_component_versions "
        "internally: if every 'Component' object is already up to date, this "
        "is a no-op and returns {'updated': false, 'reason': 'already current'}. "
        "Otherwise, for each outdated component, fetches a short description "
        "of the new release (from the component's GitHub repository, over "
        "the same safe HTTP path check_component_versions uses -- this never "
        "shells out to git or clones a repository), asks construct_knowledge "
        "to turn that into knowledge-structure objects, and merges the result "
        "into the graph's session via evolve_knowledge before re-registering "
        "it under the same name with register_graph. Returns "
        "{'updated': true, 'components_updated': [...]} on success. If no LLM "
        "provider is configured for construct_knowledge (no local Ollama, no "
        "ANTHROPIC_API_KEY), returns {'error': 'LLM provider required'} "
        "without modifying the graph."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "The registered name of the graph to update, e.g. "
                    "'cks-ecosystem'."
                ),
            },
        },
        "required": ["name"],
    },
}
