"""Input schema definition for the dead_letter_conflict_task tool."""

from __future__ import annotations

DEAD_LETTER_CONFLICT_TASK_SCHEMA = {
    "name": "dead_letter_conflict_task",
    "description": "Permanently retire a conflict task (claimed via claim_conflict_task) "
    "that could not be resolved with confidence, instead of scheduling another retry via "
    "fail_conflict_task. The task is kept (status='DEAD') for later human/operator review "
    "via list_dead_lettered_conflicts rather than retried forever or silently dropped.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "The task_id returned by claim_conflict_task.",
            },
            "error": {
                "type": "string",
                "description": "Why this conflict could not be resolved, stored as last_error.",
            },
        },
        "required": ["task_id", "error"],
    },
}
