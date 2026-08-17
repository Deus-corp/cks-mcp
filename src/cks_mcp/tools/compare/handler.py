"""
compare_versions: structural diff between session versions.
"""

from __future__ import annotations

from typing import Any

from cks.evolution import (
    AddObject,
    AddRelation,
    RemoveObject,
    RemoveRelation,
    RenameObject,
)
from cks_runtime.runtime import Runtime
from cks_runtime.session.reconstruct import reconstruct_with_retry

from cks_mcp.errors import missing_parameter


def _serialize_operators(payload: list[Any]) -> list[dict[str, Any]]:
    """Convert StructuralOperator objects to plain dicts."""
    serialized = []
    for op in payload:
        if isinstance(op, AddObject):
            serialized.append(
                {
                    "type": "add_object",
                    "identity": {
                        "id": op.obj.identity.id,
                        "type": op.obj.identity.type,
                        "name": op.obj.identity.name,
                    },
                }
            )
        elif isinstance(op, RemoveRelation):
            serialized.append(
                {
                    "type": "remove_relation",
                    "relation_id": op.relation_id,
                }
            )
        elif isinstance(op, RemoveObject):
            serialized.append(
                {
                    "type": "remove_object",
                    "object_id": op.object_id,
                }
            )
        elif isinstance(op, AddRelation):
            serialized.append(
                {
                    "type": "add_relation",
                    "identity": {
                        "id": op.relation.identity.id,
                        "type": op.relation.identity.type,
                        "name": op.relation.identity.name,
                    },
                }
            )
        elif isinstance(op, RenameObject):
            serialized.append(
                {
                    "type": "rename_object",
                    "object_id": op.object_id,
                    "new_name": op.new_name,
                }
            )
    return serialized


def _build_summary(operations: list[dict[str, Any]]) -> dict[str, int]:
    """Build a lightweight semantic summary from serialized operations."""
    summary = {
        "added_objects": 0,
        "removed_objects": 0,
        "added_relations": 0,
        "removed_relations": 0,
        "renamed_objects": 0,
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
        elif op_type == "rename_object":
            summary["renamed_objects"] += 1
    return summary


async def compare_versions(
    runtime: Runtime,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Compare a base version to the current session state using reconstruction."""
    session_id = arguments.get("session_id")
    target_version_id = arguments.get("target_version_id")

    if not session_id:
        return missing_parameter("session_id")
    if not target_version_id:
        return missing_parameter("target_version_id")

    session = runtime.get_session(session_id)
    if session is None:
        return {"error": f"Session '{session_id}' not found."}

    # Reconstruct the base version's structure using the new delta-aware
    # method. A state-hash mismatch can be a transient
    # snapshot-consistency race rather than genuine corruption, so
    # reload the session once from storage and retry before giving up.
    try:
        base_structure = await reconstruct_with_retry(
            runtime.storage, session_id, session, target_version_id, runtime.core_bridge
        )
    except ValueError as exc:
        return {
            "error": f"Failed to reconstruct base version '{target_version_id}': {exc!s}"
        }

    # Compute diff: base → current
    try:
        patch = runtime.core_bridge.diff(
            source=base_structure,
            target=session.knowledge_structure,
        )
    except Exception as e:
        return {"error": f"Failed to compute diff: {e!s}"}

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