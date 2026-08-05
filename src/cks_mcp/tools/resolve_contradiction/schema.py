"""Input schema definition for the resolve_contradiction tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code (same convention as every other
tool's schema.py, e.g. resolve_temporal_conflict's).
"""

from __future__ import annotations

from cks_mcp.tools._shared import CONTRADICTION_RULE_EXAMPLES

RESOLVE_CONTRADICTION_SCHEMA = {
    "name": "resolve_contradiction",
    "description": (
        "Resolve a contradiction_detected task (ContradictionSweeper, "
        "cks-runtime) -- a MutualExclusionRule/FunctionalRelationRule "
        "violation, per cks-core's opt-in mutual_exclusion/"
        "functional_relation extension constraints. Mechanical only: no "
        "auto_resolve/LLM path. Called with only 'session_id', it is "
        "read-only and returns every currently-live contradiction in the "
        "session (same shape as detect_contradictions, plus each one's "
        "raw 'relation_ids'). Called with 'contradiction_ids' (the 'id' "
        "field from that read-only list), it resolves each one by "
        "removing the alphabetically-first relation id among its "
        "conflicting relation set -- a simple, deterministic heuristic, "
        "not a domain judgment about which relation is 'correct'. An id "
        "that no longer matches a live contradiction (already resolved) "
        "is reported as an error for that item rather than silently "
        "skipped. Pass 'commit': true to apply the combined "
        "remove_relation operations via evolve_knowledge immediately; "
        "otherwise the operations are returned for the caller to apply "
        "itself.\n"
        + CONTRADICTION_RULE_EXAMPLES
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session to detect/resolve contradictions in.",
            },
            "contradiction_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional. Ids of contradictions to resolve (the "
                    "'id' field from a prior no-argument call to this "
                    "tool, or a contradiction_detected task's payload "
                    "'location'). Omit to only list currently-live "
                    "contradictions without resolving any."
                ),
            },
            "commit": {
                "type": "boolean",
                "description": (
                    "If true, apply the resolution to 'session_id' via "
                    "evolve_knowledge and return the result as "
                    "'commit_result'. Only has an effect when "
                    "'contradiction_ids' produced at least one operation."
                ),
            },
        },
        "required": ["session_id"],
    },
}
