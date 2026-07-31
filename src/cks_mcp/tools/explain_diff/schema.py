"""Input schema definitions for the explain_diff tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

EXPLAIN_DIFF_SCHEMA = {
    "name": "explain_diff",
    "description": "Explain the differences between the current state of a session and a "
    "target version in plain English. Useful for understanding what changed "
    "without parsing raw diff output.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session to analyze.",
            },
            "target_version_id": {
                "type": "string",
                "description": "The version to compare against.",
            },
        },
        "required": ["session_id", "target_version_id"],
    },
}
