"""Input schema definitions for the suggest_evolution tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

SUGGEST_EVOLUTION_SCHEMA = {
    "name": "suggest_evolution",
    "description": "Given a session and a description of what to change, return the current "
    "objects/relations and guidance for constructing valid evolution operations. "
    "Use this before evolve_knowledge to reduce trial-and-error. If you already "
    "have a candidate 'operations' list (same format evolve_knowledge accepts), "
    "pass it here first to preview whether it would be valid -- this dry-runs it "
    "the same way evolve_knowledge does internally, but commits nothing, so you "
    "can check correctness before spending a real evolve_knowledge call on a guess.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session to inspect.",
            },
            "description": {
                "type": "string",
                "description": "What you want to change (e.g. 'add a new Concept about photosynthesis').",
            },
            "operations": {
                "type": "array",
                "description": (
                    "Optional. A candidate list of evolution operations (same format as "
                    "evolve_knowledge's 'operations') to preview instead of getting a template. "
                    "Nothing is committed either way."
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["session_id", "description"],
    },
}
