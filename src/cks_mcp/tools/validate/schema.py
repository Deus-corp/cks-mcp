"""Input schema definitions for the validate_knowledge tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

from cks_mcp.tools._shared import CONTRADICTION_RULE_EXAMPLES, JSON_DATA_DESCRIPTION

VALIDATE_KNOWLEDGE_SCHEMA = {
    "name": "validate_knowledge",
    "description": "Validate a Canonical Knowledge Structure. Returns validation result and diagnostics. "
    "Optionally accepts 'session_id' to validate an existing session's current state instead "
    "of creating a new one. Optionally accepts 'extensions' to opt into additional, non-default "
    "validation rules for this call only (see 'extensions' parameter). "
    "Returns a 'session_id' that can be used with list_versions and revert_version to track and manage version history.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "json_data": {
                "type": "string",
                "description": JSON_DATA_DESCRIPTION,
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional. If provided, validate the current structure of this session "
                    "instead of creating a new session from json_data."
                ),
            },
            "extensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of opt-in validation extensions to apply for this call "
                    "only (does not affect other calls). Currently available: "
                    "'embedding_projection', 'verification_record', 'type_hierarchy', "
                    "'relation_type', 'mutual_exclusion', 'functional_relation', "
                    "'inference_referential_integrity', 'confidence_bounds', "
                    "'supersession_chain', 'inference_confidence_conflict', "
                    "'claim_integrity' (see ADR-001: "
                    "these apply to 'InferenceStep' objects -- "
                    "{'identity': {'id': ..., 'type': 'InferenceStep', 'name': ...}, "
                    "'structure': {'premises': [...], 'conclusion': <object_id>, "
                    "'operator': 'deductive|inductive|abductive|heuristic', "
                    "'confidence': 0.0-1.0, 'justification': ..., "
                    "'alternatives_considered': [...], 'superseded_by': <object_id> | null}}. "
                    "'inference_confidence_conflict' flags active (non-superseded) "
                    "InferenceSteps that share a conclusion but disagree on confidence, "
                    "at WARNING severity rather than ERROR). "
                    + CONTRADICTION_RULE_EXAMPLES
                    + " Example of a correct EmbeddingProjection with its 'represents' relation: "
                    '{"objects": ['
                    '{"identity": {"id": "src-1", "type": "Document", "name": "Real paper"}, "structure": {}}, '
                    '{"identity": {"id": "proj-1", "type": "EmbeddingProjection", "name": "projection"}, "structure": {"store_ref": "vecdb://xyz"}}, '
                    '{"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["src-1", "proj-1"], "relation_type": "represents"}}'
                    "]}."
                    " Example of TypeDefinition and TypeRule for ontology validation: "
                    '{"objects": ['
                    '{"identity": {"id": "td-1", "type": "TypeDefinition", "name": "Planet"}, "structure": {"type_name": "Planet", "parent_type": "CelestialBody"}}, '
                    '{"identity": {"id": "tr-1", "type": "TypeRule", "name": "orbits rule"}, "structure": {"relation_type": "orbits", "allowed_source_types": ["Planet", "Moon"], "allowed_target_types": ["Star", "Planet"]}}'
                    "]}."
                    " Example of a valid Claim ('claim_integrity'): "
                    '{"objects": ['
                    '{"identity": {"id": "claim-1", "type": "Claim", "name": "Earth orbits Sun"}, '
                    '"structure": {"statement": "The Earth orbits the Sun.", "confidence": 0.97, '
                    '"author": "researcher-agent", "created_at": "2026-08-15T00:00:00Z", '
                    '"status": "accepted", "supporting_claims": [], "contradicting_claims": []}}'
                    "]}."
                ),
            },
        },
        "required": ["json_data"],
    },
}
