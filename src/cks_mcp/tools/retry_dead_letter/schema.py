"""Input schema definition for the retry_dead_letter tool."""

from __future__ import annotations

RETRY_DEAD_LETTER_SCHEMA = {
    "name": "retry_dead_letter",
    "description": "Return a DEAD-lettered conflict task (see list_dead_lettered_conflicts) to the "
    "PENDING queue for another processing attempt, once whatever caused it to be "
    "dead-lettered via dead_letter_conflict_task has been addressed. Unlike "
    "approve_resolution/reject_resolution, this does not apply or discard a resolution -- "
    "it simply makes the task eligible for claim_conflict_task again, with retry_count and "
    "last_error reset. Fails if task_id does not exist or is not currently DEAD (e.g. it is "
    "PENDING, IN_PROGRESS, or already claimed by another retry).",
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