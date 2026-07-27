"""
explain_diff: human-readable explanation of changes between two versions.
"""

from typing import Any

from cks_runtime.runtime import Runtime
from cks_mcp.errors import missing_parameter, session_not_found


def explain_diff(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Explain the differences between the current state and a target version."""
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    target_version_id = arguments.get("target_version_id")
    if not target_version_id:
        return missing_parameter("target_version_id")

    # Reconstruct the base version's state
    try:
        base_structure = session.get_version_state(target_version_id, runtime.core_bridge)
    except ValueError as exc:
        return {"error": f"Failed to reconstruct base version '{target_version_id}': {str(exc)}"}

    # Compute diff
    try:
        patch = runtime.core_bridge.diff(
            source=base_structure,
            target=session.knowledge_structure,
        )
    except Exception as e:
        return {"error": f"Failed to compute diff: {str(e)}"}

    # Build human-readable explanation
    added_objects = []
    removed_objects = []
    added_relations = []
    removed_relations = []

    for op in patch:
        if hasattr(op, '_obj'):
            obj = op._obj
            added_objects.append({
                "id": obj.identity.id,
                "type": obj.identity.type,
                "name": obj.identity.name,
            })
        elif hasattr(op, '_object_id'):
            removed_objects.append({"id": op._object_id})
        elif hasattr(op, '_relation_id'):
            removed_relations.append({"id": op._relation_id})
        elif hasattr(op, '_relation'):
            rel = op._relation
            added_relations.append({
                "id": rel.identity.id,
                "type": rel.relation_type,
                "participants": list(rel.participants),
            })

    # Natural language summary
    summary_parts = []
    if added_objects:
        summary_parts.append(
            f"Added {len(added_objects)} object(s): "
            + ", ".join(f"{o['name']} ({o['type']})" for o in added_objects)
        )
    if removed_objects:
        summary_parts.append(
            f"Removed {len(removed_objects)} object(s): "
            + ", ".join(o['id'] for o in removed_objects)
        )
    if added_relations:
        summary_parts.append(
            f"Added {len(added_relations)} relation(s)"
        )
    if removed_relations:
        summary_parts.append(
            f"Removed {len(removed_relations)} relation(s)"
        )

    if not summary_parts:
        summary_parts.append("No changes detected.")

    return {
        "session_id": session_id,
        "base_version_id": target_version_id,
        "summary": " ".join(summary_parts),
        "details": {
            "added_objects": added_objects,
            "removed_objects": removed_objects,
            "added_relations": added_relations,
            "removed_relations": removed_relations,
        },
    }