"""Input schema definitions for the explain_knowledge tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

from cks_mcp.tools._shared import JSON_DATA_DESCRIPTION

EXPLAIN_KNOWLEDGE_SCHEMA = {
    "name": "explain_knowledge",
    "description": "Produce a human-readable explanation of a Knowledge Structure. "
    "Optionally accepts 'session_id' to explain the current state of an existing session.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "json_data": {
                "type": "string",
                "description": JSON_DATA_DESCRIPTION,
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional. If provided, explain the current structure of this session "
                    "instead of creating a new session from json_data."
                ),
            },
        },
        "required": ["json_data"],
    },
}
