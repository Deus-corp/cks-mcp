"""Input schema definition for the explain_graph tool."""

from __future__ import annotations

EXPLAIN_GRAPH_SCHEMA = {
    "name": "explain_graph",
    "description": (
        "Generate a human-readable Markdown report describing a "
        "registered ecosystem graph (register_graph), so an LLM or a "
        "person can understand its structure without parsing raw "
        "JSON. Looks up the graph by name via get_graph, loads its "
        "session, and walks session.knowledge_structure.objects, "
        "grouping them by identity.type (Component, Module, "
        "StorageBackend, Sweeper, Agent, Tool, ADR, Plugin, "
        "Interface, Task) into report sections, and using generic "
        "relation objects (structure.relation_type + "
        "structure.participants) to link related objects together "
        "(e.g. a Module under its owning Component). Purely "
        "mechanical -- no LLM calls, no network requests. Returns "
        "{'found': true, 'name': ..., 'session_id': ..., 'report': "
        "'<markdown text>'}. Returns {'found': false} if no graph is "
        "registered under that name, or {'found': true, 'error': "
        "'session_not_available', ...} if the graph's session isn't "
        "currently loaded."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "The registered name of the graph to explain, e.g. "
                    "'cks-ecosystem'."
                ),
            },
        },
        "required": ["name"],
    },
}
