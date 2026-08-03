"""Input schema definition for the claim_conflict_task tool."""

from __future__ import annotations

CLAIM_CONFLICT_TASK_SCHEMA = {
    "name": "claim_conflict_task",
    "description": "Atomically claim the next pending conflict task of a given type "
    "('gossip_conflict' or 'inference_conflict') from the persistent outbox, for a "
    "Critic agent running as a separate process (its own Runtime, so it cannot see "
    "the in-process ConflictInbox that list_gossip_conflicts/list_inference_conflicts "
    "read). Only works when the storage backend is SQLite or Postgres "
    "(CKS_STORAGE_BACKEND) -- returns supported=false under the default in-memory "
    "backend. Marks the task IN_PROGRESS so a second Critic-agent process polling "
    "concurrently cannot claim it too. Follow up with complete_conflict_task, "
    "fail_conflict_task, or dead_letter_conflict_task once you've acted on it.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "task_type": {
                "type": "string",
                "enum": ["gossip_conflict", "inference_conflict"],
                "description": "Which kind of conflict task to claim.",
            },
        },
        "required": ["task_type"],
    },
}
