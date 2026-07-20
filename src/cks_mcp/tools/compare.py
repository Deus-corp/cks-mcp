"""compare_versions: structural diff between sessions or versions."""

from typing import Any
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import DiffOperation
from cks_runtime.execution.operation_executor import OperationStatus

def compare_versions(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Compute the structural difference between the current state of a session and a target version."""
    session_id = arguments.get("session_id")
    target_version_id = arguments.get("target_version_id")

    if not session_id:
        return {"error": "Missing required parameter: session_id"}
    if not target_version_id:
        return {"error": "Missing required parameter: target_version_id"}

    session = runtime.get_session(session_id)
    if not session:
        return {"error": f"Session '{session_id}' not found."}

    tx = runtime.begin_transaction(session)
    tx.add_operation(DiffOperation("diff", target_version_id=target_version_id))
    version = runtime.commit_transaction(tx)

    result = tx.results[0] if tx.results else None
    if not result or result.status == OperationStatus.FAILED:
        return {"error": f"Failed to compute diff: {result.error if result else 'unknown'}"}

    # Convert operator objects to plain dicts for JSON serialization
    changes = []
    for op in result.payload:
        if hasattr(op, '_object_id'):
            changes.append({"type": "remove_object", "object_id": op._object_id})
        elif hasattr(op, '_relation_id'):
            changes.append({"type": "remove_relation", "relation_id": op._relation_id})
        elif hasattr(op, '_obj'):
            changes.append({"type": "add_object", "identity": {"id": op._obj.identity.id, "type": op._obj.identity.type, "name": op._obj.identity.name}})
        elif hasattr(op, '_relation'):
            changes.append({"type": "add_relation", "identity": {"id": op._relation.identity.id, "type": op._relation.identity.type, "name": op._relation.identity.name}})

    return {
        "session_id": session.session_id,
        "target_version_id": target_version_id,
        "changes": changes,
    }