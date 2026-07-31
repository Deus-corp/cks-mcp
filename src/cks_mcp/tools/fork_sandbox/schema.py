"""Input schema definitions for the fork_sandbox tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

FORK_SANDBOX_SCHEMA = {
    "name": "fork_sandbox",
    "description": "Create an isolated sandbox branch from a parent session, "
    "optionally apply a hypothesis (list of evolution operations) "
    "immediately, and show how the sandbox differs from its fork "
    "point. The parent session is never touched. Safe to discard "
    "with close_session if the hypothesis doesn't pan out.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The parent session to fork from.",
            },
            "version_id": {
                "type": "string",
                "description": "Optional. Fork from this historical version instead of the current state.",
            },
            "hypothesis": {
                "type": "string",
                "description": "Optional. A short description of the hypothesis (for logging/reporting).",
            },
            "operations": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Optional. Evolution operations to apply immediately in the sandbox.",
            },
        },
        "required": ["session_id"],
    },
}
