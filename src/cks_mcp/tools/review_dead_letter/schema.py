"""Input schema definition for the review_dead_letter tool."""

from __future__ import annotations

REVIEW_DEAD_LETTER_SCHEMA = {
    "name": "review_dead_letter",
    "description": (
        "Look up a single DEAD-lettered conflict task (see "
        "list_dead_lettered_conflicts) and propose a ready-to-apply "
        "resolution for it, so resolving it does not require knowing each "
        "conflict-resolution tool's own parameter shape. Mechanical only -- "
        "never calls an LLM, never applies anything. Returns the task's own "
        "fields (task_type, session_id, payload, retry_count, last_error) "
        "plus 'proposed_resolution': {'tool': <resolution tool name>, "
        "'arguments': {...}} that can be passed straight to "
        "approve_resolution, optionally with manual edits (e.g. a different "
        "winner_id). Returns an error if task_id is not currently "
        "dead-lettered, or if the payload doesn't carry enough information "
        "to propose a resolution (proposed_resolution.error is set in that "
        "case, with a message explaining what's missing)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "The task_id of a DEAD-lettered task (from list_dead_lettered_conflicts).",
            },
        },
        "required": ["task_id"],
    },
}
