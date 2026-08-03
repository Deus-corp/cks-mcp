"""Input schema definition for the list_dead_lettered_conflicts tool."""

from __future__ import annotations

LIST_DEAD_LETTERED_CONFLICTS_SCHEMA = {
    "name": "list_dead_lettered_conflicts",
    "description": "Return every conflict task a Critic agent has permanently given up "
    "on (via dead_letter_conflict_task), oldest first, for human/operator review. "
    "Read-only -- unlike claim_conflict_task, this never removes anything from the "
    "outbox. Returns an empty list (supported=false) under a storage backend that "
    "doesn't support the outbox (e.g. the default in-memory backend).",
    "inputSchema": {
        "type": "object",
        "properties": {
            "task_type": {
                "type": "string",
                "enum": ["gossip_conflict", "inference_conflict"],
                "description": "Only return dead-lettered tasks of this type. Omit for both.",
            },
        },
        "required": [],
    },
}
