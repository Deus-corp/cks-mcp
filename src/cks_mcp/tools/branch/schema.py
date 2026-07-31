"""Input schema definitions for the create_branch, close_session tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

CREATE_BRANCH_SCHEMA = {
    "name": "create_branch",
    "description": "Fork a new session from an existing one. Use this to isolate an "
    "experiment, explore an alternative modeling approach, or try a "
    "risky edit without touching the parent session -- if the branch "
    "doesn't pan out, close_session it; if it does, merge_branch it "
    "back into the parent.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The parent session to branch from.",
            },
            "version_id": {
                "type": "string",
                "description": (
                    "Optional. Fork from this specific historical version "
                    "of the parent instead of its current state. Recommended "
                    "when you intend to merge_branch the result back later: "
                    "it records the exact fork point merge_branch needs as "
                    "its merge base. Without it, merge_branch has no "
                    "automatic fork point and requires an explicit "
                    "'base_version_id' itself."
                ),
            },
        },
        "required": ["session_id"],
    },
}

CLOSE_SESSION_SCHEMA = {
    "name": "close_session",
    "description": "Close a session, releasing it from the runtime. Typical use: "
    "after merge_branch reports success, close_session the source "
    "branch that was just merged in -- it has been integrated and no "
    "longer needs to stay open.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session to close.",
            },
        },
        "required": ["session_id"],
    },
}
