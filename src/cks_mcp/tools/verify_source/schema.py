"""Input schema definitions for the verify_source tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

VERIFY_SOURCE_SCHEMA = {
    "name": "verify_source",
    "description": "Verify an external source by performing a real HTTP request. Creates a VerificationRecord that can be validated.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL of the source to verify.",
            },
            "subject_id": {
                "type": "string",
                "description": "The ID of the Knowledge Object that this verification is about.",
            },
        },
        "required": ["url", "subject_id"],
    },
}
