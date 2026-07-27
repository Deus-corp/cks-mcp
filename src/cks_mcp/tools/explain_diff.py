"""
explain_diff: human-readable explanation of changes between two versions.
"""

from typing import Any

from cks import AddObject, AddRelation, RemoveObject, RemoveRelation
from cks_runtime.runtime import Runtime
from cks_mcp.errors import missing_parameter, session_not_found
from cks_mcp.diffing import field_level_diff


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

    current_structure = session.knowledge_structure

    # Compute diff
    try:
        patch = runtime.core_bridge.diff(
            source=base_structure,
            target=current_structure,
        )
    except Exception as e:
        return {"error": f"Failed to compute diff: {str(e)}"}

    touched_object_ids: set[str] = set()
    touched_relation_ids: set[str] = set()

    for op in patch:
        if isinstance(op, (AddObject, RemoveObject)):
            touched_object_ids.add(
                op._obj.identity.id if isinstance(op, AddObject) else op._object_id
            )
        elif isinstance(op, (AddRelation, RemoveRelation)):
            touched_relation_ids.add(
                op._relation.identity.id if isinstance(op, AddRelation) else op._relation_id
            )

    def _classify(ids: set[str]) -> dict[str, list[dict[str, Any]]]:
        buckets: dict[str, list[dict[str, Any]]] = {
            "added": [], "deleted": [], "modified": [], "unchanged": [],
        }
        for identity_id in sorted(ids):
            diff_entry = field_level_diff(base_structure.get(identity_id), current_structure.get(identity_id))
            action = diff_entry.get("action")
            if action in buckets:
                buckets[action].append({"id": identity_id, **diff_entry})
        return buckets

    object_buckets = _classify(touched_object_ids)
    relation_buckets = _classify(touched_relation_ids)

    added_objects = object_buckets["added"]
    removed_objects = object_buckets["deleted"]
    modified_objects = object_buckets["modified"]

    added_relations = relation_buckets["added"]
    removed_relations = relation_buckets["deleted"]
    modified_relations = relation_buckets["modified"]
    relinked_relations = relation_buckets["unchanged"]

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
            + ", ".join(f"{o['name']} ({o['type']})" for o in removed_objects)
        )
    if modified_objects:
        summary_parts.append(
            f"Modified {len(modified_objects)} object(s): "
            + ", ".join(f"{o['name']} ({o['type']})" for o in modified_objects)
        )
    if added_relations:
        summary_parts.append(f"Added {len(added_relations)} relation(s)")
    if removed_relations:
        summary_parts.append(f"Removed {len(removed_relations)} relation(s)")
    if modified_relations:
        summary_parts.append(f"Modified {len(modified_relations)} relation(s)")
    if relinked_relations:
        summary_parts.append(
            f"Re-linked {len(relinked_relations)} relation(s) with no actual "
            "change (one of their participants was replaced elsewhere in this diff)"
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
            "modified_objects": modified_objects,
            "added_relations": added_relations,
            "removed_relations": removed_relations,
            "modified_relations": modified_relations,
            "relinked_relations": relinked_relations,
        },
    }