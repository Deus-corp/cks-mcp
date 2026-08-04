"""Input schema definition for the resolve_temporal_conflict tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code (same convention as every other
tool's schema.py, e.g. refresh_verification's).
"""

from __future__ import annotations

RESOLVE_TEMPORAL_CONFLICT_SCHEMA = {
    "name": "resolve_temporal_conflict",
    "description": (
        "Resolve a temporal_conflict task (ADR-011's "
        "TemporalStalenessSweeper: a KnowledgeObject whose 'valid_until' "
        "has passed, per cks-core's opt-in TemporalValidityConstraint / "
        "ADR-003) by applying one of three actions to the expired object: "
        "'bump' extends 'valid_until' forward by 'extend_by_days' days "
        "(anchored to now, or to the object's current valid_until if that "
        "is somehow still in the future); 'archive' marks the object as "
        "archived and removes 'valid_until' so it is no longer flagged as "
        "expired or re-escalated by a future sweep, while keeping the "
        "object itself (and any relations referencing it) intact; "
        "'ignore' is a pure acknowledgment that leaves the object "
        "unchanged. Unlike arbitrate_inference_conflict/"
        "resolve_gossip_conflict, there is no auto_resolve (LLM) path -- "
        "deciding which action fits an expired fact is a domain judgment "
        "only the caller can make; applying the chosen action is purely "
        "mechanical, via evolve_knowledge. Pass 'commit': true to apply "
        "the change to the session immediately instead of only returning "
        "the operation for the caller to apply itself ('ignore' never "
        "produces an operation, so 'commit' has no effect for it)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session containing the expired object.",
            },
            "object_id": {
                "type": "string",
                "description": (
                    "The id of the expired KnowledgeObject (the "
                    "temporal_conflict task's 'object_id')."
                ),
            },
            "action": {
                "type": "string",
                "enum": ["bump", "archive", "ignore"],
                "description": (
                    "The resolution to apply. 'bump' extends 'valid_until' "
                    "(requires 'extend_by_days'). 'archive' retires the "
                    "object. 'ignore' acknowledges the conflict without "
                    "changing anything. Defaults to 'ignore' if omitted."
                ),
            },
            "extend_by_days": {
                "type": "number",
                "description": (
                    "Required when action is 'bump'. Number of days to "
                    "extend 'valid_until' by, measured from now (or from "
                    "the object's current 'valid_until' if that is later "
                    "than now). Must be positive."
                ),
            },
            "commit": {
                "type": "boolean",
                "description": (
                    "If true, apply the resolution to 'session_id' via "
                    "evolve_knowledge and return the result as "
                    "'commit_result'. Has no effect when action is "
                    "'ignore', since that action never produces an "
                    "operation to commit."
                ),
            },
        },
        "required": ["session_id", "object_id"],
    },
}