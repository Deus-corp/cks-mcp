"""Input schema definition for the reject_resolution tool."""

from __future__ import annotations

REJECT_RESOLUTION_SCHEMA = {
    "name": "reject_resolution",
    "description": (
        "Decline a proposed resolution for a DEAD-lettered conflict task, "
        "recording why via the task's 'last_error'. The task is left in "
        "the DEAD state -- this never retries and never removes it, it "
        "only annotates it for the next reviewer (see review_dead_letter / "
        "list_dead_lettered_conflicts)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "The task_id of a DEAD-lettered task (from list_dead_lettered_conflicts).",
            },
            "reason": {
                "type": "string",
                "description": "Optional explanation for why the proposed resolution was rejected.",
            },
        },
        "required": ["task_id"],
    },
}
