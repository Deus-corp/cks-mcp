"""Input schema definition for the approve_resolution tool."""

from __future__ import annotations

APPROVE_RESOLUTION_SCHEMA = {
    "name": "approve_resolution",
    "description": (
        "Apply a resolution to a DEAD-lettered conflict task -- typically "
        "the 'proposed_resolution' a prior review_dead_letter call returned "
        "for the same task_id, optionally with manual edits (e.g. a "
        "different winner_id). Mechanical only: validates that "
        "resolution.tool is the correct resolution tool for the task's own "
        "task_type (an error if it isn't -- e.g. a gossip resolution cannot "
        "be applied to an inference_conflict task), calls that tool with "
        "resolution.arguments, and -- only if the call succeeds -- marks "
        "the task complete via complete_conflict_task, removing it from the "
        "dead-letter queue. If the resolution does not succeed, the task is "
        "left unchanged (still DEAD) and 'approved' is false; retry with a "
        "different resolution, or use reject_resolution to record why it "
        "was declined."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "integer",
                "description": "The task_id of a DEAD-lettered task (from list_dead_lettered_conflicts).",
            },
            "resolution": {
                "type": "object",
                "description": (
                    "The resolution to apply: {'tool': <resolution tool "
                    "name>, 'arguments': {...}}. Normally the "
                    "'proposed_resolution' object returned by review_dead_letter "
                    "for the same task_id, optionally with manual edits."
                ),
                "properties": {
                    "tool": {
                        "type": "string",
                        "enum": [
                            "resolve_gossip_conflict",
                            "arbitrate_inference_conflict",
                            "refresh_verification",
                            "resolve_temporal_conflict",
                            "resolve_contradiction",
                        ],
                        "description": "Name of the resolution tool to call.",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments to pass to that resolution tool.",
                    },
                },
                "required": ["tool", "arguments"],
            },
        },
        "required": ["task_id", "resolution"],
    },
}
