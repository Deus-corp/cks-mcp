"""Input schema definitions for the explain_knowledge tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

from cks_mcp.tools._shared import JSON_DATA_DESCRIPTION

EXPLAIN_KNOWLEDGE_SCHEMA = {
    "name": "explain_knowledge",
    "description": "Produce a human-readable explanation of a Knowledge Structure. "
    "Optionally accepts 'session_id' to explain the current state of an existing session. "
    "Optionally accepts 'object_id' to answer 'why is this object believed?' instead: "
    "walks the active InferenceStep chain(s) concluding that object back to base facts.",
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
            "object_id": {
                "type": "string",
                "description": (
                    "Optional. If provided, explain *why* this specific object is "
                    "currently believed instead of producing the general structure-wide "
                    "explanation: recursively walks every active InferenceStep chain "
                    "concluding this object through its premises down to base facts, plus "
                    "the belief's supersession history. Requires an attached Core that "
                    "implements the explain_inference capability."
                ),
            },
        },
        "required": ["json_data"],
    },
}
