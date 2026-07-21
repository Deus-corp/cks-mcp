"""
compare_versions: structural diff between session versions.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime
from cks_runtime.execution.operation_executor import OperationStatus


def _serialize_operators(payload: list[Any]) -> list[dict[str, Any]]:
    """Convert StructuralOperator objects to plain dicts."""
    serialized = []
    for op in payload:
        if hasattr(op, '_obj'):
            serialized.append({
                "type": "add_object",
                "identity": {
                    "id": op._obj.identity.id,
                    "type": op._obj.identity.type,
                    "name": op._obj.identity.name,
                },
            })
        elif hasattr(op, '_relation_id'):
            serialized.append({
                "type": "remove_relation",
                "relation_id": op._relation_id,
            })
        elif hasattr(op, '_object_id'):
            serialized.append({
                "type": "remove_object",
                "object_id": op._object_id,
            })
        elif hasattr(op, '_relation'):
            serialized.append({
                "type": "add_relation",
                "identity": {
                    "id": op._relation.identity.id,
                    "type": op._relation.identity.type,
                    "name": op._relation.identity.name,
                },
            })
    return serialized


def _build_summary(operations: list[dict[str, Any]]) -> dict[str, int]:
    """Build a lightweight semantic summary from serialized operations."""
    summary = {
        "added_objects": 0,
        "removed_objects": 0,
        "added_relations": 0,
        "removed_relations": 0,
    }
    for op in operations:
        op_type = op.get("type")
        if op_type == "add_object":
            summary["added_objects"] += 1
        elif op_type == "remove_object":
            summary["removed_objects"] += 1
        elif op_type == "add_relation":
            summary["added_relations"] += 1
        elif op_type == "remove_relation":
            summary["removed_relations"] += 1
    return summary


def compare_versions(
    runtime: Runtime,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Compare a base version to the current session state using reconstruction."""
    session_id = arguments.get("session_id")
    target_version_id = arguments.get("target_version_id")

    if not session_id:
        return {"error": "Missing required parameter: session_id"}
    if not target_version_id:
        return {"error": "Missing required parameter: target_version_id"}

    session = runtime.get_session(session_id)
    if session is None:
        return {"error": f"Session '{session_id}' not found."}

    # Reconstruct the base version's structure using the new delta-aware method
    try:
        base_structure = session.get_version_state(target_version_id, runtime.core_bridge)
    except ValueError as exc:
        return {"error": f"Failed to reconstruct base version '{target_version_id}': {str(exc)}"}

    # Compute diff: base → current
    try:
        patch = runtime.core_bridge.diff(
            source=base_structure,
            target=session.knowledge_structure,
        )
    except Exception as e:
        return {"error": f"Failed to compute diff: {str(e)}"}

    serialized_ops = _serialize_operators(patch)

    current_version_id = None
    if session.version_history:
        current_version_id = session.version_history[-1].version_id

    return {
        "session_id": session.session_id,
        "base_version_id": target_version_id,
        "current_version_id": current_version_id,
        "direction": "base_to_current",
        "summary": _build_summary(serialized_ops),
        "operations": serialized_ops,
    }