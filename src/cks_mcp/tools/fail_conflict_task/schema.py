"""Input schema definition for the fail_conflict_task tool."""

from __future__ import annotations

FAIL_CONFLICT_TASK_SCHEMA = {
    "name": "fail_conflict_task",
    "description": "Mark a conflict task (claimed via claim_conflict_task) as "
    "transiently failed, scheduling it for another attempt with exponential "
    "backoff (2^retry_count seconds, capped at 1 hour) -- the same policy "
    "OutboxEmbeddingWorker uses for projection tasks. Pass retry_count as the "
    "claimed task's own retry_count plus one. Use dead_letter_conflict_task "
    "instead if you've given up on this conflict rather than hit a transient error.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "The task_id returned by claim_conflict_task.",
            },
            "retry_count": {
                "type": "integer",
                "description": "The new retry count (claimed task's retry_count + 1).",
            },
            "error": {
                "type": "string",
                "description": "Why this attempt failed, stored as the task's last_error.",
            },
        },
        "required": ["task_id", "retry_count", "error"],
    },
}
