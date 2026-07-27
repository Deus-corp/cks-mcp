"""
suggest_evolution: propose valid evolution operations based on a description.
"""

from typing import Any

from cks_runtime.runtime import Runtime
from cks_mcp.errors import missing_parameter, session_not_found


def suggest_evolution(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Given a session and a description of what to change, suggest a list of
    evolution operations that the caller can review and then pass to
    evolve_knowledge.
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

    # This tool does NOT generate operations itself — it provides a template
    # and guidance for the LLM to generate valid operations.
    # The caller (LLM) should use the information below to construct
    # a correct operations list for evolve_knowledge.

    existing_objects = [
        {
            "id": obj.identity.id,
            "type": obj.identity.type,
            "name": obj.identity.name,
        }
        for obj in session.knowledge_structure.objects
        if not hasattr(obj, 'participants')  # exclude relations
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
            "construct a JSON list of operations for evolve_knowledge. "
            "Run a dry-run with validate_knowledge if you want to check correctness before committing."
        ),
    }