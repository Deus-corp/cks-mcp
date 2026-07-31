"""Input schema definitions for the export_session tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

EXPORT_SESSION_SCHEMA = {
    "name": "export_session",
    "description": "Export a full session bundle for migration or archival. "
    "Unlike export_knowledge (which converts to RDF/JSON-LD), this tool "
    "packages the session's current structure, version history, and metadata "
    "into a self-contained JSON document that can be used to recreate the "
    "session in another runtime instance. "
    "Supports two formats: 'bundle' (default) — a complete migration envelope "
    "with version history; 'cks' — bare canonical CKS JSON of the current "
    "structure only. Set 'include_structures' to true to embed the full "
    "KnowledgeStructure for each historical version (may be large).",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session to export.",
            },
            "format": {
                "type": "string",
                "description": (
                    "Output format: 'bundle' (default) — full migration envelope "
                    "with metadata and version history; 'cks' — current structure only."
                ),
            },
            "include_structures": {
                "type": "boolean",
                "description": (
                    "Optional. When true and format='bundle', embed the serialized "
                    "KnowledgeStructure for each version in the history (may produce "
                    "a large payload for long-lived sessions). Default false."
                ),
            },
        },
        "required": ["session_id"],
    },
}
