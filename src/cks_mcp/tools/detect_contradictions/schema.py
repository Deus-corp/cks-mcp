"""Input schema definitions for the detect_contradictions tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

from cks_mcp.tools._shared import CONTRADICTION_RULE_EXAMPLES

DETECT_CONTRADICTIONS_SCHEMA = {
    "name": "detect_contradictions",
    "description": "Detect logical contradictions in a Knowledge Structure using "
    "the contradiction extension constraints. "
    "Supports two types of contradiction detection:\n"
    "- mutual_exclusion: Flags when the same source-target pair has both of two declared relation types.\n"
    "- functional_relation: Flags when a source has multiple targets via a declared single-valued relation type.\n"
    + CONTRADICTION_RULE_EXAMPLES
    + "\nTo use, ensure your structure contains MutualExclusionRule and/or FunctionalRelationRule objects.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Optional. Session whose structure to check for contradictions.",
            },
            "json_data": {
                "type": "string",
                "description": "Optional. JSON Knowledge Structure to check (if no session_id).",
            },
        },
    },
}
