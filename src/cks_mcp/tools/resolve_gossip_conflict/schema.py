"""Input schema definition for the resolve_gossip_conflict tool."""

from __future__ import annotations

RESOLVE_GOSSIP_CONFLICT_SCHEMA = {
    "name": "resolve_gossip_conflict",
    "description": (
        "Resolve a structural gossip merge conflict between two sessions. "
        "Like arbitrate_inference_conflict for inference conflicts, this tool "
        "has three paths: (1) interactive -- returns the conflicting objects "
        "with their diffs and a resolution policy, expecting the caller to "
        "supply a 'resolutions' dict on the next call; (2) unattended -- "
        "set 'auto_resolve': true to have an LLM propose resolutions; "
        "(3) bypass -- caller can always hand-craft resolutions and call "
        "merge_branch directly."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "target_session_id": {
                "type": "string",
                "description": "The target session for merge_branch."
            },
            "source_session_id": {
                "type": "string",
                "description": "The source/branch session for merge_branch."
            },
            "auto_resolve": {
                "type": "boolean",
                "description": "If true, call an LLM to propose resolutions."
            },
            "model": {
                "type": "string",
                "description": "Optional model override for auto_resolve."
            },
            "max_tokens": {
                "type": "integer",
                "description": "Optional max_tokens override for auto_resolve."
            },
        },
        "required": ["target_session_id", "source_session_id"],
    },
}