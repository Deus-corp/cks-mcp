"""Input schema definitions for the export_knowledge tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

EXPORT_KNOWLEDGE_SCHEMA = {
    "name": "export_knowledge",
    "description": "Export a session's Knowledge Structure to another format. "
    "Supports 'json-ld', 'turtle', and 'rdf-xml'.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session to export.",
            },
            "format": {
                "type": "string",
                "description": "Output format: 'json-ld', 'turtle', or 'rdf-xml'. Default 'json-ld'.",
            },
        },
        "required": ["session_id"],
    },
}
