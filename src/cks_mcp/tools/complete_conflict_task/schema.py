"""Input schema definition for the complete_conflict_task tool."""

from __future__ import annotations

COMPLETE_CONFLICT_TASK_SCHEMA = {
    "name": "complete_conflict_task",
    "description": "Mark a conflict task (claimed via claim_conflict_task) as "
    "successfully resolved, removing it from the outbox permanently. Call this "
    "after you've resolved the underlying conflict, e.g. via merge_branch for a "
    "gossip_conflict or arbitrate_inference_conflict for an inference_conflict.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "The task_id returned by claim_conflict_task.",
            },
        },
        "required": ["task_id"],
    },
}
