"""Input schema definitions for the compare_versions tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

COMPARE_VERSIONS_SCHEMA = {
    "name": "compare_versions",
    "description": "Compare the current state of a session against a target version. "
    "The returned diff is directional. "
    "'direction' explicitly describes how to interpret the changes. "
    "'base_version_id' is the historical version being compared against. "
    "'target_version_id' is the current session state. "
    "The response also contains a semantic summary (added/removed objects "
    "and relations) to make interpretation easier for LLMs.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session whose current state will be compared.",
            },
            "target_version_id": {
                "type": "string",
                "description": (
                    "Historical version to compare against. "
                    "The comparison is performed between this version "
                    "and the current state of the session."
                ),
            },
        },
        "required": ["session_id", "target_version_id"],
    },
}
