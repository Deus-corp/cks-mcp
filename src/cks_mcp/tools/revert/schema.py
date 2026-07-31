"""Input schema definitions for the list_versions, revert_version tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

LIST_VERSIONS_SCHEMA = {
    "name": "list_versions",
    "description": "List all available versions of a session's history. Requires a 'session_id' obtained from a previous call to validate_knowledge or evolve_knowledge.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The ID of the session to list versions for.",
            }
        },
        "required": ["session_id"],
    },
}

REVERT_VERSION_SCHEMA = {
    "name": "revert_version",
    "description": "Revert a session's Knowledge Structure to a specific previous version. Requires a 'session_id' obtained from a previous call to validate_knowledge or evolve_knowledge.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The ID of the session to revert.",
            },
            "target_version_id": {
                "type": "string",
                "description": "The ID of the version to revert to.",
            },
        },
        "required": ["session_id", "target_version_id"],
    },
}
