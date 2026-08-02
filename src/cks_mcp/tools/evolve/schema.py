"""Input schema definitions for the evolve_knowledge tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

from cks_mcp.tools._shared import JSON_DATA_DESCRIPTION

EVOLVE_KNOWLEDGE_SCHEMA = {
    "name": "evolve_knowledge",
    "description": "Apply structural evolution operators to a Knowledge Structure. "
    "Returns a new 'session_id' and 'version_id'. The 'session_id' can be used with list_versions and revert_version. "
    "Optionally accepts 'extensions' to opt into additional, non-default validation rules "
    "when checking the evolved structure before commit (see 'extensions' parameter).",
    "inputSchema": {
        "type": "object",
        "properties": {
            "json_data": {
                "type": "string",
                "description": JSON_DATA_DESCRIPTION,
            },
            "operations": {
                "type": "array",
                "description": (
                    "List of evolution operators to apply, in order. Each operator is an "
                    "object with a 'type' field; the other required fields depend on that "
                    "type and are NOT interchangeable between operators:\n"
                    "  - 'add_object': requires 'identity' ({'id','type','name'}) and "
                    "optional 'structure' (a free-form dict). Fails if the id already "
                    "exists -- use 'update_object' to change an existing object instead.\n"
                    "  - 'add_relation': requires 'identity', 'participants' (list of "
                    "existing object ids), 'relation_type', and optional 'structure'.\n"
                    "  - 'remove_object': requires 'object_id' (NOT 'identity'). Removing "
                    "an object also cascade-removes every relation that references it; "
                    "the response's 'cascade_removed_relations' lists what was removed.\n"
                    "  - 'remove_relation': requires 'relation_id' (NOT 'identity'). Only "
                    "valid for an id that is actually a relation -- use 'remove_object' "
                    "for a plain object.\n"
                    "  - 'update_object': requires 'object_id' and 'structure_patch' (a "
                    "dict of fields to change), and optional 'mode' ('merge', the default "
                    "-- shallow-merges structure_patch into the existing structure, and a "
                    "patch value of null deletes that key -- or 'replace', which replaces "
                    "the whole structure dict). Use this instead of remove_object + "
                    "add_object to change an object's content: the object's id and every "
                    "relation referencing it are left untouched, with no cascade.\n"
                    "  - 'rename_object': requires 'object_id' and 'new_name'. Changes "
                    "only the human-readable identity.name of an existing object or "
                    "relation, leaving its id, type, structure, and every referencing "
                    "relation completely untouched — zero cascade, no relation rebuild.\n"
                    "  - 'resolve_inference_conflict': requires 'conclusion_id' and "
                    "'winner_id'. Resolves an InferenceConfidenceConflict (see ADR-001): "
                    "supersedes every other active InferenceStep concluding "
                    "'conclusion_id' in favor of 'winner_id', by setting each one's "
                    "'superseded_by' to 'winner_id'. 'winner_id' must reference an "
                    "existing, active InferenceStep whose own 'conclusion' already "
                    "equals 'conclusion_id'. A no-op if 'winner_id' is already the only "
                    "active step (nothing left to resolve). Pass "
                    "'inference_confidence_conflict' and 'supersession_chain' in this "
                    "call's 'extensions' to have the result checked at commit time.\n"
                    "Example: "
                    '\'[{"type": "add_object", "identity": {"id": "obj-2", "type": "Lemma", '
                    '"name": "New"}, "structure": {}}, {"type": "add_relation", "identity": '
                    '{"id": "rel-1", "type": "Relation", "name": "r"}, "participants": '
                    '["obj-1", "obj-2"], "relation_type": "derives"}, {"type": '
                    '"update_object", "object_id": "obj-1", "structure_patch": '
                    '{"summary": "revised text"}}, {"type": "rename_object", '
                    '"object_id": "obj-2", "new_name": "Renamed Lemma"}]\'.'
                ),
            },
            "session_id": {
                "type": "string",
                "description": (
                    "Optional. If provided, evolve the current structure of this session "
                    "instead of creating a new session from json_data."
                ),
            },
            "extensions": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of opt-in validation extensions to apply to the "
                    "commit-time validation of the evolved structure, for this call only "
                    "(same names as validate_knowledge's 'extensions', e.g. "
                    "'inference_referential_integrity', 'confidence_bounds', "
                    "'supersession_chain', 'inference_confidence_conflict', "
                    "'stale_premise'). Without this, evolving InferenceStep fields "
                    "(directly via 'update_object', or via "
                    "'resolve_inference_conflict') is only checked against the always-on "
                    "built-in constraints, not the reasoning-domain ones."
                ),
            },
        },
        "required": ["json_data"],
    },
}