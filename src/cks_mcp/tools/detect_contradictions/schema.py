"""Input schema definitions for the detect_contradictions tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

from cks_mcp.tools._shared import CONTRADICTION_RULE_EXAMPLES

DETECT_CONTRADICTIONS_SCHEMA = {
    "name": "detect_contradictions",
    "description": "Detect logical contradictions in a Knowledge Structure using "
    "the contradiction/conflict extension constraints. "
    "Supports three types of detection:\n"
    "- mutual_exclusion: Flags when the same source-target pair has both of two declared relation types.\n"
    "- functional_relation: Flags when a source has multiple targets via a declared single-valued relation type.\n"
    "- inference_confidence_conflict (see ADR-001): Flags when two or more active (non-superseded) "
    "InferenceStep objects share a 'conclusion' but disagree on 'confidence'. Reported at WARNING "
    "severity, not ERROR -- this is a resolvable belief conflict between agreeing inference paths, "
    "not a jointly-nonsensical relation pair. Mark a step no longer active with its own "
    "'superseded_by' field, not by editing another step.\n"
    + CONTRADICTION_RULE_EXAMPLES
    + "\nTo use mutual_exclusion/functional_relation, ensure your structure contains MutualExclusionRule "
    "and/or FunctionalRelationRule objects. inference_confidence_conflict needs no rule object -- it "
    "applies to any InferenceStep objects present.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Optional. Session whose structure to check for contradictions.",
            },
            "json_data": {
                "type": "string",
                "description": "Optional. JSON Knowledge Structure to check (if no session_id).",
            },
        },
    },
}
