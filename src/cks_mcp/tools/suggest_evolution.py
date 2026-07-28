"""
suggest_evolution: propose valid evolution operations based on a description,
and optionally preview a concrete set of operations before committing them.
"""

from typing import Any

import cks
from cks.core import CanonicalRelation
from cks.evolution import parse_operations
from cks_runtime.operations.operation_types import EvolveOperation
from cks_runtime.runtime import Runtime

from cks_mcp.errors import missing_parameter, session_not_found


def _preview_operations(
    runtime: Runtime, session: Any, session_id: str, operations_data: list[dict[str, Any]]
) -> dict[str, Any]:
    """Dry-run ``operations_data`` against ``session`` without committing.

    Mirrors the exact dry-run idiom `evolve_knowledge` uses to check an
    evolution before it commits (see tools/evolve.py): execute the same
    `EvolveOperation` through the executor with `record_metrics=False`
    so this probe never shows up in get_metrics, then validate the
    prospective result with `cks.validate()`. Nothing is persisted --
    no transaction is opened, no version is created -- regardless of
    whether the proposed operations are valid.
    """
    try:
        operations = parse_operations(operations_data)
    except ValueError as exc:
        return {
            "error": "invalid_operations",
            "message": f"Could not parse 'operations': {exc}",
        }
    if not operations:
        return {"error": "no_operations", "message": "No evolution operations were provided."}

    structure = session.knowledge_structure
    op = EvolveOperation("evolve", knowledge_structure=structure, evolution=operations)
    result = runtime.executor.execute(op, session, record_metrics=False)
    if result.status.value == "failed":
        return {
            "session_id": session_id,
            "would_apply": False,
            "message": f"Evolution failed: {result.error}",
        }

    prospective_structure = result.payload
    validation = cks.validate(prospective_structure)
    response: dict[str, Any] = {
        "session_id": session_id,
        "would_apply": validation.is_valid,
        "operations_previewed": len(operations),
        "diagnostics": [
            {
                "code": d.identity,
                "severity": d.severity.value,
                "message": d.message,
                "location": d.location,
            }
            for d in validation.diagnostics
        ],
        "note": (
            "This is a preview only -- nothing has been committed. Call "
            "evolve_knowledge with the same 'operations' to apply them."
            if validation.is_valid
            else "This is a preview only -- nothing has been committed. Fix "
            "the diagnostics above before calling evolve_knowledge."
        ),
    }
    if validation.is_valid:
        response["preview_serialized"] = runtime.core_bridge.serialize(prospective_structure)
    return response


def suggest_evolution(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Given a session and a description of what to change, suggest a list of
    evolution operations that the caller can review and then pass to
    evolve_knowledge.

    If the caller already has a candidate 'operations' list (the same
    format evolve_knowledge accepts), pass it to preview what committing
    it would do: this runs the exact same dry-run validation
    evolve_knowledge runs internally, but returns instead of committing,
    so the caller can check correctness before spending a real
    evolve_knowledge call (and a real version) on a guess.
    """
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    description = arguments.get("description", "")
    if not description.strip():
        return {"error": "missing_parameter", "message": "Description must not be empty."}

    operations_data = arguments.get("operations")
    if operations_data:
        return _preview_operations(runtime, session, session_id, operations_data)

    # No candidate operations yet — this tool does NOT generate operations
    # itself, it provides a template and guidance for the LLM to generate
    # valid operations. The caller (LLM) should use the information below
    # to construct a correct operations list, optionally previewing it by
    # calling this same tool again with 'operations' set.

    existing_objects = [
        {
            "id": obj.identity.id,
            "type": obj.identity.type,
            "name": obj.identity.name,
        }
        for obj in session.knowledge_structure.objects
        if not isinstance(obj, CanonicalRelation)  # exclude relations
    ]

    existing_relations = [
        {
            "id": rel.identity.id,
            "type": rel.relation_type,
            "participants": list(rel.participants),
        }
        for rel in session.knowledge_structure.relations()
    ]

    return {
        "description": description,
        "current_objects": existing_objects,
        "current_relations": existing_relations,
        "available_operation_types": [
            "add_object — requires 'identity' ({'id','type','name'}) and optional 'structure'",
            "add_relation — requires 'identity', 'participants' (list), 'relation_type', optional 'structure'",
            "remove_object — requires 'object_id' (cascades to relations)",
            "remove_relation — requires 'relation_id'",
            "update_object — requires 'object_id' and 'structure_patch', optional 'mode' ('merge' or 'replace')",
        ],
        "guidance": (
            "Based on the description above and the current objects/relations listed, "
            "construct a JSON list of operations. Call this same tool again with that "
            "list as 'operations' to preview it (no commit), or pass it directly to "
            "evolve_knowledge to apply it."
        ),
    }